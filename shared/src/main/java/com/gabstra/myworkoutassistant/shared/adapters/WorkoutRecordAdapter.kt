package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.google.gson.JsonDeserializationContext
import com.google.gson.JsonDeserializer
import com.google.gson.JsonElement
import com.google.gson.JsonObject
import com.google.gson.JsonSerializationContext
import com.google.gson.JsonSerializer
import java.lang.reflect.Type
import java.time.LocalDateTime
import java.util.UUID

class WorkoutRecordAdapter : JsonSerializer<WorkoutRecord>, JsonDeserializer<WorkoutRecord> {
    override fun serialize(
        src: WorkoutRecord,
        typeOfSrc: Type,
        context: JsonSerializationContext
    ): JsonElement {
        return JsonObject().apply {
            addProperty("id", src.id.toString())
            addProperty("workoutId", src.workoutId.toString())
            addProperty("workoutHistoryId", src.workoutHistoryId.toString())
            addProperty("setIndex", src.setIndex.toLong())
            addProperty("exerciseId", src.exerciseId.toString())
            addProperty("ownerDevice", src.ownerDevice)
            add("lastActiveSyncAt", context.serialize(src.lastActiveSyncAt, LocalDateTime::class.java))
            addProperty("activeSessionRevision", src.activeSessionRevision.toLong())
            if (src.lastKnownSessionState != null) {
                addProperty("lastKnownSessionState", src.lastKnownSessionState)
            }
        }
    }

    override fun deserialize(
        json: JsonElement,
        typeOfT: Type,
        context: JsonDeserializationContext
    ): WorkoutRecord {
        val obj = json.asJsonObject
        return WorkoutRecord(
            id = UUID.fromString(obj.requiredString("id")),
            workoutId = UUID.fromString(obj.requiredString("workoutId")),
            workoutHistoryId = UUID.fromString(obj.requiredString("workoutHistoryId")),
            setIndex = obj.optionalUInt("setIndex"),
            exerciseId = UUID.fromString(obj.requiredString("exerciseId")),
            ownerDevice = obj.optionalString("ownerDevice") ?: "PHONE",
            lastActiveSyncAt = obj.get("lastActiveSyncAt")?.let { element ->
                context.deserialize<LocalDateTime?>(element, LocalDateTime::class.java)
            },
            activeSessionRevision = obj.optionalUInt("activeSessionRevision"),
            lastKnownSessionState = obj.optionalString("lastKnownSessionState"),
        )
    }

    private fun JsonObject.requiredString(name: String): String =
        get(name)?.takeIf { !it.isJsonNull }?.asString
            ?: throw IllegalArgumentException("Missing required WorkoutRecord field '$name'")

    private fun JsonObject.optionalString(name: String): String? =
        get(name)?.takeIf { !it.isJsonNull }?.asString

    private fun JsonObject.optionalUInt(name: String): UInt =
        get(name)?.takeIf { !it.isJsonNull }?.asLong?.toUInt() ?: 0u
}
