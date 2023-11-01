package com.gabstra.myworkoutassistant.shared

import androidx.compose.runtime.mutableStateOf
import com.google.gson.Gson
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.io.File

class WorkoutStoreRepository(private val filesDir:File) : IWorkoutStoreRepository {
    override fun getWorkoutStore(): WorkoutStore {
        var workoutStore: WorkoutStore? = null
        val gson = Gson()
        // Assuming you have a consistent filename pattern or a single file
        val filename = "workout_store.json"
        val file = File(filesDir, filename)
        if (file.exists()) {
            val jsonString = file.readText()
            workoutStore = gson.fromJson(jsonString, WorkoutStore::class.java)
        }
        return workoutStore ?: WorkoutStore(emptyList())  // Return the result or a default value
    }

    override fun saveWorkoutStore(workoutStore: WorkoutStore) {
        val gson = Gson()
        val jsonString = gson.toJson(workoutStore)
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