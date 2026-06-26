package com.gabstra.myworkoutassistant.e2e.fixtures

import android.content.Context
import com.gabstra.myworkoutassistant.shared.motion.ExerciseMovementRef
import java.util.UUID

object ZercherMovementWorkoutStoreFixture {
    const val WORKOUT_NAME = "Zercher Squat Movement Preview"
    const val MOVEMENT_ID = "barbell-zercher-squat"
    private const val MOVEMENT_ASSET_NAME = "barbell_zercher_squat_wear_skeleton.json"

    val EXERCISE_ID: UUID = UUID.fromString("5b534a2c-1ebc-47cc-bbc3-c5378b2134d6")

    fun readMovementJson(context: Context): String =
        context.assets.open(MOVEMENT_ASSET_NAME)
            .bufferedReader(Charsets.UTF_8)
            .use { reader -> reader.readText().trim() }

    fun movementRef(movementJson: String): ExerciseMovementRef =
        ExerciseMovementRef.forWearSkeletonJson(MOVEMENT_ID, movementJson)
}
