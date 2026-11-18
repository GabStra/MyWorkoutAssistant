package com.gabstra.myworkoutassistant.shared.datalayer

import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.gson.Gson
import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.google.gson.JsonParseException
import com.google.gson.JsonParser
import java.util.UUID

/**
 * The two workout-definition fields a watch can author during a session.
 *
 * The watch sends one explicit intent per edit instead of asking the phone to infer edits from a
 * whole session-hydrated store snapshot. That distinction matters because progression/history
 * hydration legitimately changes set values on the watch without changing the phone definition.
 */
enum class WatchWorkoutDefinitionEditKind {
    EXERCISE_EQUIPMENT,
    LOAD_CALIBRATION,
}

enum class WatchWorkoutSetKind {
    WEIGHT,
    BODY_WEIGHT,
}

/**
 * A single set value the watch changed during calibration.
 *
 * [baseWeight] / [baseSubCategory] are the values the watch observed immediately before applying
 * the calibration. The phone only applies [newWeight] / [newSubCategory] when its current set still
 * matches that base, so a concurrent same-field phone edit is detected instead of overwritten.
 * The intent's [WatchWorkoutDefinitionEditIntent.baseEquipmentId] similarly guards against a
 * concurrent equipment change.
 */
data class WatchWorkoutSetEdit(
    val setId: UUID,
    val setKind: WatchWorkoutSetKind,
    val baseWeight: Double? = null,
    val newWeight: Double? = null,
    val baseSubCategory: SetSubCategory,
    val newSubCategory: SetSubCategory,
)

/**
 * Structured watch-originated definition edit.
 *
 * [workoutId] is the exact version the watch edited. A newer version with the same
 * [workoutGlobalId] is reported as stale rather than silently targeted by content.
 */
data class WatchWorkoutDefinitionEditIntent(
    val workoutId: UUID,
    val workoutGlobalId: UUID,
    val exerciseId: UUID,
    val kind: WatchWorkoutDefinitionEditKind,
    val baseEquipmentId: UUID? = null,
    val newEquipmentId: UUID? = null,
    val baseRequiresLoadCalibration: Boolean = false,
    val setEdits: List<WatchWorkoutSetEdit> = emptyList(),
) {
    companion object {
        fun equipment(
            workout: Workout,
            exercise: Exercise,
            newEquipmentId: UUID?,
        ) = WatchWorkoutDefinitionEditIntent(
            workoutId = workout.id,
            workoutGlobalId = workout.globalId,
            exerciseId = exercise.id,
            kind = WatchWorkoutDefinitionEditKind.EXERCISE_EQUIPMENT,
            baseEquipmentId = exercise.equipmentId,
            newEquipmentId = newEquipmentId,
        )

        /**
         * Builds a calibration intent from the watch's persisted workout definition and the sets
         * produced by [com.gabstra.myworkoutassistant.shared.workout.rir.updateWorkSetsInExercise].
         *
         * The baseline must come from [persistedWorkout] / [persistedExercise], not from the
         * session-hydrated selected workout: progression/history legitimately changes set values
         * during the session, while the phone still holds the persisted definition. The calibrated
         * [calibratedSets] are matched to the persisted definition by set id, and only a matching
         * id may contribute a [WatchWorkoutSetEdit].
         *
         * Returns null when neither a persisted set changed nor the definition still requires
         * calibration.
         */
        fun calibration(
            persistedWorkout: Workout,
            persistedExercise: Exercise,
            calibratedSets: List<Set>,
        ): WatchWorkoutDefinitionEditIntent? {
            val persistedSetsById = persistedExercise.sets.associateBy { it.id }
            val setEdits = calibratedSets.mapNotNull { calibratedSet ->
                val persistedSet = persistedSetsById[calibratedSet.id]
                    ?: return@mapNotNull null
                buildSetEdit(persistedSet, calibratedSet)
            }
            if (setEdits.isEmpty() && !persistedExercise.requiresLoadCalibration) return null
            return WatchWorkoutDefinitionEditIntent(
                workoutId = persistedWorkout.id,
                workoutGlobalId = persistedWorkout.globalId,
                exerciseId = persistedExercise.id,
                kind = WatchWorkoutDefinitionEditKind.LOAD_CALIBRATION,
                baseEquipmentId = persistedExercise.equipmentId,
                baseRequiresLoadCalibration = persistedExercise.requiresLoadCalibration,
                setEdits = setEdits,
            )
        }

        private fun buildSetEdit(
            persistedSet: Set,
            calibratedSet: Set,
        ): WatchWorkoutSetEdit? = when {
            persistedSet is WeightSet && calibratedSet is WeightSet -> {
                if (
                    persistedSet.weight == calibratedSet.weight &&
                    persistedSet.subCategory == calibratedSet.subCategory
                ) {
                    null
                } else {
                    WatchWorkoutSetEdit(
                        setId = calibratedSet.id,
                        setKind = WatchWorkoutSetKind.WEIGHT,
                        baseWeight = persistedSet.weight,
                        newWeight = calibratedSet.weight,
                        baseSubCategory = persistedSet.subCategory,
                        newSubCategory = calibratedSet.subCategory,
                    )
                }
            }
            persistedSet is BodyWeightSet && calibratedSet is BodyWeightSet -> {
                if (
                    persistedSet.additionalWeight == calibratedSet.additionalWeight &&
                    persistedSet.subCategory == calibratedSet.subCategory
                ) {
                    null
                } else {
                    WatchWorkoutSetEdit(
                        setId = calibratedSet.id,
                        setKind = WatchWorkoutSetKind.BODY_WEIGHT,
                        baseWeight = persistedSet.additionalWeight,
                        newWeight = calibratedSet.additionalWeight,
                        baseSubCategory = persistedSet.subCategory,
                        newSubCategory = calibratedSet.subCategory,
                    )
                }
            }
            else -> null
        }
    }
}

/** Finds exactly one exercise prescription in this workout, including supersets. */
fun Workout.findExercisePrescription(exerciseId: UUID): Exercise? =
    workoutComponents.findExercises(exerciseId).singleOrNull()

private fun List<WorkoutComponent>.findExercises(exerciseId: UUID): List<Exercise> =
    flatMap { component ->
        when (component) {
            is Exercise -> if (component.id == exerciseId) listOf(component) else emptyList()
            is Superset -> component.exercises.filter { it.id == exerciseId }
            else -> emptyList()
        }
    }

/** Stable, reflection-free JSON representation used in the DataMap. */
object WatchWorkoutDefinitionEditCodec {
    private val gson = Gson()

    fun encode(intent: WatchWorkoutDefinitionEditIntent): String {
        val payload = JsonObject().apply {
            addProperty("workoutId", intent.workoutId.toString())
            addProperty("workoutGlobalId", intent.workoutGlobalId.toString())
            addProperty("exerciseId", intent.exerciseId.toString())
            addProperty("kind", intent.kind.name)
            intent.baseEquipmentId?.let { addProperty("baseEquipmentId", it.toString()) }
            intent.newEquipmentId?.let { addProperty("newEquipmentId", it.toString()) }
            addProperty("baseRequiresLoadCalibration", intent.baseRequiresLoadCalibration)
            add(
                "setEdits",
                JsonArray().apply {
                    intent.setEdits.forEach { edit ->
                        add(
                            JsonObject().apply {
                                addProperty("setId", edit.setId.toString())
                                addProperty("setKind", edit.setKind.name)
                                edit.baseWeight?.let { addProperty("baseWeight", it) }
                                edit.newWeight?.let { addProperty("newWeight", it) }
                                addProperty("baseSubCategory", edit.baseSubCategory.name)
                                addProperty("newSubCategory", edit.newSubCategory.name)
                            },
                        )
                    }
                },
            )
        }
        return gson.toJson(payload)
    }

    fun decode(json: String): WatchWorkoutDefinitionEditIntent =
        try {
            val payload = JsonParser.parseString(json).asJsonObject
            WatchWorkoutDefinitionEditIntent(
                workoutId = requiredUuid(payload.requiredString("workoutId"), "workoutId"),
                workoutGlobalId = requiredUuid(
                    payload.requiredString("workoutGlobalId"),
                    "workoutGlobalId",
                ),
                exerciseId = requiredUuid(payload.requiredString("exerciseId"), "exerciseId"),
                kind = requiredEnum(payload.requiredString("kind"), "kind"),
                baseEquipmentId = optionalUuid(payload.optionalString("baseEquipmentId"), "baseEquipmentId"),
                newEquipmentId = optionalUuid(payload.optionalString("newEquipmentId"), "newEquipmentId"),
                baseRequiresLoadCalibration = payload.optionalBoolean("baseRequiresLoadCalibration"),
                setEdits = payload.optionalArray("setEdits").map { element ->
                    val setEdit = element.asJsonObject
                    WatchWorkoutSetEdit(
                        setId = requiredUuid(setEdit.requiredString("setId"), "setEdit.setId"),
                        setKind = requiredEnum(setEdit.requiredString("setKind"), "setEdit.setKind"),
                        baseWeight = setEdit.optionalDouble("baseWeight"),
                        newWeight = setEdit.optionalDouble("newWeight"),
                        baseSubCategory = requiredEnum(
                            setEdit.requiredString("baseSubCategory"),
                            "setEdit.baseSubCategory",
                        ),
                        newSubCategory = requiredEnum(
                            setEdit.requiredString("newSubCategory"),
                            "setEdit.newSubCategory",
                        ),
                    )
                },
            )
        } catch (exception: JsonParseException) {
            throw exception
        } catch (exception: RuntimeException) {
            throw JsonParseException("Malformed workout definition edit intent", exception)
        }
}

private fun JsonObject.requiredString(field: String): String =
    optionalString(field) ?: throw JsonParseException("Missing $field")

private fun JsonObject.optionalString(field: String): String? {
    val element = get(field) ?: return null
    if (element.isJsonNull) return null
    if (!element.isJsonPrimitive || !element.asJsonPrimitive.isString) {
        throw JsonParseException("Invalid $field")
    }
    return element.asString
}

private fun JsonObject.optionalBoolean(field: String): Boolean {
    val element = get(field) ?: return false
    if (element.isJsonNull) return false
    if (!element.isJsonPrimitive || !element.asJsonPrimitive.isBoolean) {
        throw JsonParseException("Invalid $field")
    }
    return element.asBoolean
}

private fun JsonObject.optionalDouble(field: String): Double? {
    val element = get(field) ?: return null
    if (element.isJsonNull) return null
    if (!element.isJsonPrimitive || !element.asJsonPrimitive.isNumber) {
        throw JsonParseException("Invalid $field")
    }
    return element.asDouble
}

private fun JsonObject.optionalArray(field: String): List<com.google.gson.JsonElement> {
    val element = get(field) ?: return emptyList()
    if (element.isJsonNull) return emptyList()
    if (!element.isJsonArray) throw JsonParseException("Invalid $field")
    return element.asJsonArray.toList()
}

private fun requiredUuid(value: String?, field: String): UUID =
    value?.let { raw ->
        try {
            UUID.fromString(raw)
        } catch (exception: IllegalArgumentException) {
            throw JsonParseException("Invalid $field", exception)
        }
    } ?: throw JsonParseException("Missing $field")

private fun optionalUuid(value: String?, field: String): UUID? =
    value?.let { raw ->
        try {
            UUID.fromString(raw)
        } catch (exception: IllegalArgumentException) {
            throw JsonParseException("Invalid $field", exception)
        }
    }

private inline fun <reified T : Enum<T>> requiredEnum(value: String?, field: String): T =
    value?.let { raw ->
        try {
            enumValueOf<T>(raw)
        } catch (exception: IllegalArgumentException) {
            throw JsonParseException("Invalid $field", exception)
        }
    } ?: throw JsonParseException("Missing $field")
