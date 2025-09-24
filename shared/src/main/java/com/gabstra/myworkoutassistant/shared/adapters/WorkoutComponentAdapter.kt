package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.getExerciseTypeFromSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
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

class WorkoutComponentAdapter : JsonSerializer<WorkoutComponent>,
    JsonDeserializer<WorkoutComponent> {
    override fun serialize(
        src: WorkoutComponent,
        typeOfSrc: Type,
        context: JsonSerializationContext
    ): JsonElement {
        val jsonObject = JsonObject()
        val workoutComponentType = when (src) {
            is Exercise -> "Exercise"
            is Rest -> "Rest"
            is Superset -> "Superset"
            else -> throw RuntimeException("Unsupported workout component type")
        }

        jsonObject.addProperty("id", src.id.toString())
        jsonObject.addProperty("type", workoutComponentType)


        when (src) {
            is Exercise -> {
                jsonObject.addProperty("enabled", src.enabled)
                jsonObject.addProperty("name", src.name)
                jsonObject.addProperty("doNotStoreHistory", src.doNotStoreHistory)
                jsonObject.addProperty("notes", src.notes)
                jsonObject.add("sets", context.serialize(src.sets))
                jsonObject.addProperty("exerciseType", src.exerciseType.name)

                jsonObject.addProperty("minLoadPercent", src.minLoadPercent)
                jsonObject.addProperty("maxLoadPercent", src.maxLoadPercent)
                jsonObject.addProperty("minReps", src.minReps)
                jsonObject.addProperty("maxReps", src.maxReps)

                if (src.lowerBoundMaxHRPercent != null) {
                    jsonObject.addProperty("lowerBoundMaxHRPercent", src.lowerBoundMaxHRPercent)
                }
                if (src.upperBoundMaxHRPercent != null) {
                    jsonObject.addProperty("upperBoundMaxHRPercent", src.upperBoundMaxHRPercent)
                }
                if (src.equipmentId != null) {
                    jsonObject.addProperty("equipmentId", src.equipmentId.toString())
                }

                if (src.bodyWeightPercentage != null) {
                    jsonObject.addProperty("bodyWeightPercentage", src.bodyWeightPercentage)
                }

                jsonObject.addProperty("generateWarmUpSets", src.generateWarmUpSets)
                jsonObject.addProperty("enableProgression", src.enableProgression)
                jsonObject.addProperty("keepScreenOn", src.keepScreenOn)
                jsonObject.addProperty("intraSetRestInSeconds", src.intraSetRestInSeconds)
                jsonObject.addProperty("showCountDownTimer", src.showCountDownTimer)
            }

            is Rest -> {
                jsonObject.addProperty("enabled", src.enabled)
                jsonObject.addProperty("timeInSeconds", src.timeInSeconds)
            }

            is Superset -> {
                jsonObject.addProperty("enabled", src.enabled)
                jsonObject.add("exercises", context.serialize(src.exercises))
                jsonObject.add("restSecondsByExercise", context.serialize(src.restSecondsByExercise))
            }
        }
        return jsonObject
    }

    override fun deserialize(
        json: JsonElement,
        typeOfT: Type,
        context: JsonDeserializationContext
    ): WorkoutComponent {
        val jsonObject = json.asJsonObject
        val id = UUID.fromString(jsonObject.get("id").asString)
        val type = jsonObject.get("type").asString



        val doNotStoreHistory = if (jsonObject.has("doNotStoreHistory")) {
            jsonObject.get("doNotStoreHistory").asBoolean
        } else {
            false
        }

        return when (type) {
            "Exercise" -> {
                val enabled = jsonObject.get("enabled").asBoolean
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
                val notes = if (jsonObject.has("notes")) {
                    jsonObject.get("notes").asString
                } else {
                    ""
                }


                val minLoadPercent = if (jsonObject.has("minLoadPercent")) {
                    jsonObject.get("minLoadPercent").asDouble
                } else {
                    0.0
                }

                val maxLoadPercent = if (jsonObject.has("maxLoadPercent")) {
                    jsonObject.get("maxLoadPercent").asDouble
                } else {
                    0.0
                }

                val minReps = if (jsonObject.has("minReps")) {
                    jsonObject.get("minReps").asInt
                } else {
                    0
                }

                val maxReps = if (jsonObject.has("maxReps")) {
                    jsonObject.get("maxReps").asInt
                } else {
                    0
                }

                val lowerBoundMaxHRPercent = if (jsonObject.has("lowerBoundMaxHRPercent")) {
                    jsonObject.get("lowerBoundMaxHRPercent").asFloat
                } else {
                    null
                }

                val upperBoundMaxHRPercent = if (jsonObject.has("upperBoundMaxHRPercent")) {
                    jsonObject.get("upperBoundMaxHRPercent").asFloat
                } else {
                    null
                }

                val equipmentId = if (jsonObject.has("equipmentId")) {
                    UUID.fromString(jsonObject.get("equipmentId").asString)
                } else {
                    null
                }

                val bodyWeightPercentage = if (jsonObject.has("bodyWeightPercentage")) {
                    jsonObject.get("bodyWeightPercentage").asDouble
                } else {
                    null
                }

                val generateWarmUpSets = if (jsonObject.has("generateWarmUpSets")) {
                    jsonObject.get("generateWarmUpSets").asBoolean
                } else {
                    false
                }

                val enableProgression = if (jsonObject.has("enableProgression")) {
                    jsonObject.get("enableProgression").asBoolean
                } else {
                    false
                }

                val keepScreenOn = if (jsonObject.has("keepScreenOn")) {
                    jsonObject.get("keepScreenOn").asBoolean
                } else {
                    false
                }

                val intraSetRestInSeconds = if (jsonObject.has("intraSetRestInSeconds")) {
                    jsonObject.get("intraSetRestInSeconds").asInt
                } else {
                    null
                }

                val showCountDownTimer = if (jsonObject.has("showCountDownTimer")) {
                    jsonObject.get("showCountDownTimer").asBoolean
                } else {
                    false
                }

                Exercise(
                    id,
                    enabled,
                    name,
                    doNotStoreHistory,
                    notes,
                    sets,
                    exerciseType,
                    minLoadPercent,
                    maxLoadPercent,
                    minReps,
                    maxReps,
                    lowerBoundMaxHRPercent,
                    upperBoundMaxHRPercent,
                    equipmentId,
                    bodyWeightPercentage,
                    generateWarmUpSets,
                    enableProgression,
                    keepScreenOn,
                    showCountDownTimer,
                    intraSetRestInSeconds
                )
            }

            "Rest" -> {
                val enabled = jsonObject.get("enabled").asBoolean
                val timeInSeconds = jsonObject.get("timeInSeconds").asInt
                Rest(id, enabled, timeInSeconds)
            }

            "Superset" -> {
                val enabled = jsonObject.get("enabled").asBoolean
                val exercisesType = object : TypeToken<List<Exercise>>() {}.type
                val exercises: List<Exercise> = context.deserialize(jsonObject.get("exercises"), exercisesType)

                val restSecondsByExercise = when{
                    jsonObject.has("restSecondsByExercise") -> {
                        val restMapType = object : TypeToken<Map<UUID, Int>>() {}.type
                        context.deserialize(jsonObject.get("restSecondsByExercise"), restMapType)
                    }
                    else -> {
                        val restMap = mutableMapOf<UUID, Int>()
                        exercises.forEach { exercise ->
                            restMap[exercise.id] = 0
                        }
                        restMap
                    }
                }

                Superset(id, enabled, exercises, restSecondsByExercise)
            }

            else -> throw RuntimeException("Unsupported workout component type")
        }
    }
}