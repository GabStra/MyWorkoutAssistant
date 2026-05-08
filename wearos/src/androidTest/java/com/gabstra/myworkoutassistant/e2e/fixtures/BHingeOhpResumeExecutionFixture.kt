package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import androidx.test.platform.app.InstrumentationRegistry
import com.gabstra.myworkoutassistant.shared.AppDatabase
import com.gabstra.myworkoutassistant.shared.fromJSONtoAppBackup
import com.gabstra.myworkoutassistant.shared.fromWorkoutStoreToJSON
import java.io.File
import java.util.UUID
import kotlinx.coroutines.runBlocking

object BHingeOhpResumeExecutionFixture {
    const val ASSET_NAME = "b_hinge_ohp_resume_execution_fixture.json"
    const val WORKOUT_NAME = "B — Hinge/OHP"

    val WORKOUT_ID: UUID = UUID.fromString("c63f8180-e97c-48bd-9eb6-6ce0121b5489")
    val WORKOUT_GLOBAL_ID: UUID = UUID.fromString("bd9ea8d6-44f9-4bd6-833c-4bbb2ad09060")
    val WARMUP_EXERCISE_ID: UUID = UUID.fromString("a9d92f5c-7eba-4cd8-8f60-c03996b7274e")
    val ROMANIAN_DEADLIFT_EXERCISE_ID: UUID = UUID.fromString("c8ee5566-8131-407e-b8fb-23b0cec89da0")
    val OVERHEAD_PRESS_EXERCISE_ID: UUID = UUID.fromString("d4b87722-67c1-4172-acbe-19f5fa22c87b")
    val BULGARIAN_SPLIT_SQUAT_EXERCISE_ID: UUID = UUID.fromString("cb3677b8-da29-43f3-aefa-857724c315cf")
    val EXPECTED_PRE_RESUME_COMPLETED_COUNTS: Map<UUID, Int> = mapOf(
        WARMUP_EXERCISE_ID to 1,
        ROMANIAN_DEADLIFT_EXERCISE_ID to 6,
        OVERHEAD_PRESS_EXERCISE_ID to 6,
    )

    fun setup(context: Context) {
        val backup = readBackupFromAsset(context)
        File(context.filesDir, "workout_store.json").writeText(fromWorkoutStoreToJSON(backup.WorkoutStore))
        runBlocking {
            val db = AppDatabase.getDatabase(context)
            WearFixtureDatabaseSeeder.resetResumeScenarioTables(db)
        }
    }

    private fun readBackupFromAsset(context: Context) =
        fromJSONtoAppBackup(
            sanitizeForWearE2E(
                try {
                    InstrumentationRegistry.getInstrumentation().context.assets
                        .open(ASSET_NAME)
                        .bufferedReader()
                        .use { it.readText() }
                } catch (_: Exception) {
                    context.assets.open(ASSET_NAME).bufferedReader().use { it.readText() }
                }
            )
        )

    private fun sanitizeForWearE2E(rawBackupJson: String): String =
        rawBackupJson
            .replace(
                "\"externalHeartRateConfigs\":[{\"source\":\"POLAR_BLE\",\"deviceId\":\"D1EAE32F\"},{\"source\":\"WHOOP_BLE\",\"displayName\":\"WHOOP 5A00699807\",\"connectionMode\":\"BLE_BROADCAST\"}]",
                "\"externalHeartRateConfigs\":[]"
            )
            .replace("\"keepScreenOn\":false", "\"keepScreenOn\":true")
            .replace("\"heartRateSource\":\"WHOOP_BLE\"", "\"heartRateSource\":\"WATCH_SENSOR\"")
}
