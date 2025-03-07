package com.gabstra.myworkoutassistant.shared

import java.io.File

class WorkoutStoreRepository(private val filesDir:File) : IWorkoutStoreRepository {
    override fun getWorkoutStore(): WorkoutStore {
        var workoutStore: WorkoutStore? = null

        // Assuming you have a consistent filename pattern or a single file
        val filename = "workout_store.json"
        val file = File(filesDir, filename)
        if (file.exists()) {
            val jsonString = file.readText()
            workoutStore = fromJSONToWorkoutStore(jsonString)
        }

        return workoutStore ?: WorkoutStore(emptyList(), emptyList(),null,0,0.0,0.0,0.0)  // Return the result or a default value
    }

    override fun saveWorkoutStore(workoutStore: WorkoutStore) {
        val jsonString = fromWorkoutStoreToJSON(workoutStore)
        val filename = "workout_store.json"  // Assuming a single file for the workout store
        val file = File(filesDir, filename)
        file.writeText(jsonString)  // Write the JSON string to the file
    }

    override fun saveWorkoutStoreFromJson(workoutStoreJson: String) {
        val filename = "workout_store.json"  // Assuming a single file for the workout store
        val file = File(filesDir, filename)
        file.writeText(workoutStoreJson)  // Write the JSON string to the file
    }
}