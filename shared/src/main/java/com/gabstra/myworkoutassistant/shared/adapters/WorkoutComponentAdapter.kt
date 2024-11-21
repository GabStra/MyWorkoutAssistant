package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.getExerciseTypeFromSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.utils.ProgressionHelper
import com.gabstra.myworkoutassistant.shared.utils.ProgressionHelper.getParametersByExerciseType
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
                if (src.exerciseCategory != null) {
                    jsonObject.addProperty("exerciseCategory", src.exerciseCategory.name)
                }
                jsonObject.addProperty("minLoadPercent", src.minLoadPercent)
                jsonObject.addProperty("maxLoadPercent", src.maxLoadPercent)
                jsonObject.addProperty("minReps", src.minReps)
                jsonObject.addProperty("maxReps", src.maxReps)
                jsonObject.addProperty("fatigueFactor", src.fatigueFactor)
                jsonObject.addProperty("volumeIncreasePercent", src.volumeIncreasePercent)
                if (src.targetZone != null){
                    jsonObject.addProperty("targetZone", src.targetZone)
                }
                if (src.equipmentId != null){
                    jsonObject.addProperty("equipmentId", src.equipmentId.toString())
                }
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

                val exerciseCategory = if (jsonObject.has("exerciseCategory")) {
                    ProgressionHelper.ExerciseCategory.fromString(jsonObject.get("exerciseCategory").asString)
                } else if( exerciseType == ExerciseType.WEIGHT || exerciseType == ExerciseType.BODY_WEIGHT){
                    ProgressionHelper.ExerciseCategory.HYPERTROPHY
                }else{
                    null
                }

                val minLoadPercent = if (jsonObject.has("minLoadPercent")) {
                    jsonObject.get("minLoadPercent").asDouble
                } else {
                    if(exerciseCategory != null) getParametersByExerciseType(exerciseCategory).percentLoadRange.first else 0.0
                }

                val maxLoadPercent = if (jsonObject.has("maxLoadPercent")) {
                    jsonObject.get("maxLoadPercent").asDouble
                } else {
                    if(exerciseCategory != null) getParametersByExerciseType(exerciseCategory).percentLoadRange.second else 0.0
                }

                val minReps = if (jsonObject.has("minReps")) {
                    jsonObject.get("minReps").asInt
                } else {
                    if(exerciseCategory != null) getParametersByExerciseType(exerciseCategory).repsRange.first else 0
                }

                val maxReps = if (jsonObject.has("maxReps")) {
                    jsonObject.get("maxReps").asInt
                } else {
                    if(exerciseCategory != null) getParametersByExerciseType(exerciseCategory).repsRange.last else 0
                }

                val fatigueFactor = if (jsonObject.has("fatigueFactor")) {
                    jsonObject.get("fatigueFactor").asFloat
                } else {
                    if(exerciseCategory != null) getParametersByExerciseType(exerciseCategory).fatigueFactor.toFloat() else 0.0f
                }

                val volumeIncreasePercent = if (jsonObject.has("volumeIncreasePercent")) {
                    jsonObject.get("volumeIncreasePercent").asFloat
                } else {
                    if(exerciseCategory != null) 5f else 0.0f
                }

                val targetZone = if (jsonObject.has("targetZone")) {
                    jsonObject.get("targetZone").asInt
                } else {
                   null
                }

                val equipmentId = if (jsonObject.has("equipmentId")) {
                    UUID.fromString(jsonObject.get("equipmentId").asString)
                } else {
                    null
                }

                Exercise(id,enabled, name, doNotStoreHistory,notes, sets, exerciseType,exerciseCategory, minLoadPercent, maxLoadPercent, minReps, maxReps, fatigueFactor, volumeIncreasePercent,targetZone,equipmentId)
            }
            "Rest" -> {
                val timeInSeconds = jsonObject.get("timeInSeconds").asInt
                Rest(id,enabled,timeInSeconds)
            }
            else -> throw RuntimeException("Unsupported workout component type")
        }
    }
}