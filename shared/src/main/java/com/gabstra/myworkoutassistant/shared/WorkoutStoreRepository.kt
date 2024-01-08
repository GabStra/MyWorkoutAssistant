package com.gabstra.myworkoutassistant.shared

import android.util.Log
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.adapters.SetAdapter
import com.gabstra.myworkoutassistant.shared.adapters.WorkoutComponentAdapter
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.gson.GsonBuilder
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

        return workoutStore ?: WorkoutStore(emptyList(),null,0)  // Return the result or a default value
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