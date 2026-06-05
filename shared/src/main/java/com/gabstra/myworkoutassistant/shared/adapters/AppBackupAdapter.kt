package com.gabstra.myworkoutassistant.shared.adapters

import com.gabstra.myworkoutassistant.shared.AppBackup
import com.gabstra.myworkoutassistant.shared.ErrorLog
import com.gabstra.myworkoutassistant.shared.ExerciseInfo
import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.RestHistory
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.WorkoutRecord
import com.gabstra.myworkoutassistant.shared.WorkoutSchedule
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.google.gson.JsonDeserializationContext
import com.google.gson.JsonDeserializer
import com.google.gson.JsonElement
import java.lang.reflect.Type

class AppBackupAdapter : JsonDeserializer<AppBackup> {
    override fun deserialize(
        json: JsonElement,
        typeOfT: Type,
        context: JsonDeserializationContext
    ): AppBackup {
        val jsonObject = json.asJsonObject
        return AppBackup(
            WorkoutStore = context.deserialize(jsonObject.get("WorkoutStore"), WorkoutStore::class.java),
            WorkoutHistories = deserializeList(jsonObject.get("WorkoutHistories"), context, WorkoutHistory::class.java),
            SetHistories = deserializeList(jsonObject.get("SetHistories"), context, SetHistory::class.java),
            ExerciseInfos = deserializeList(jsonObject.get("ExerciseInfos"), context, ExerciseInfo::class.java),
            WorkoutSchedules = deserializeList(jsonObject.get("WorkoutSchedules"), context, WorkoutSchedule::class.java),
            WorkoutRecords = deserializeList(jsonObject.get("WorkoutRecords"), context, WorkoutRecord::class.java),
            ExerciseSessionProgressions = deserializeList(
                jsonObject.get("ExerciseSessionProgressions"),
                context,
                ExerciseSessionProgression::class.java
            ),
            ErrorLogs = deserializeNullableList(jsonObject.get("ErrorLogs"), context, ErrorLog::class.java),
            RestHistories = deserializeNullableList(jsonObject.get("RestHistories"), context, RestHistory::class.java),
            LiteRtLmModelSourceUri = jsonObject.get("LiteRtLmModelSourceUri")
                ?.takeUnless { it.isJsonNull }
                ?.asString
        )
    }

    private fun <T> deserializeList(
        element: JsonElement?,
        context: JsonDeserializationContext,
        clazz: Class<T>
    ): List<T> {
        if (element == null || element.isJsonNull) return emptyList()
        return element.asJsonArray.map { context.deserialize<T>(it, clazz) }
    }

    private fun <T> deserializeNullableList(
        element: JsonElement?,
        context: JsonDeserializationContext,
        clazz: Class<T>
    ): List<T>? {
        if (element == null || element.isJsonNull) return null
        return deserializeList(element, context, clazz)
    }
}
