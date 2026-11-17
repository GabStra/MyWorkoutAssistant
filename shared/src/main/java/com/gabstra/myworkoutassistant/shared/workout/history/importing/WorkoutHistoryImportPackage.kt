package com.gabstra.myworkoutassistant.shared.workout.history.importing

import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.WorkoutHistory
import com.gabstra.myworkoutassistant.shared.backupGson
import com.google.gson.JsonParser

/** Append-only, profile-scoped history payload. IDs are supplied by the source and make replay idempotent. */
data class WorkoutHistoryImportPackage(
    val format: String = FORMAT,
    val formatVersion: Int = FORMAT_VERSION,
    val profileId: String,
    val workoutHistories: List<WorkoutHistory>,
    val setHistories: List<SetHistory>,
) {
    fun toJson(): String = backupGson().toJson(this)

    companion object {
        const val FORMAT = "my-workout-assistant-workout-history"
        const val FORMAT_VERSION = 1

        fun fromJson(json: String): WorkoutHistoryImportPackage {
            val root = JsonParser.parseString(json)
            require(root.isJsonObject) { "History package must be a JSON object." }
            val objectJson = root.asJsonObject
            require(objectJson.get("profileId")?.isJsonPrimitive == true) { "History package has no profile ID." }
            require(objectJson.get("workoutHistories")?.isJsonArray == true) {
                "History package has no session list."
            }
            require(objectJson.get("setHistories")?.isJsonArray == true) { "History package has no set list." }
            require(objectJson.getAsJsonArray("workoutHistories").none { it.isJsonNull }) {
                "History package contains an empty session row."
            }
            require(objectJson.getAsJsonArray("setHistories").none { it.isJsonNull }) {
                "History package contains an empty set row."
            }
            return backupGson().fromJson(objectJson, WorkoutHistoryImportPackage::class.java)
        }
    }
}
