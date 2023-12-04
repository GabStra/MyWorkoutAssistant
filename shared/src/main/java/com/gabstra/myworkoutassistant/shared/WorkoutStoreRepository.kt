package com.gabstra.myworkoutassistant.shared

import android.util.Log
import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.utils.SetAdapter
import com.gabstra.myworkoutassistant.shared.utils.WorkoutComponentAdapter
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import com.google.gson.Gson
import com.google.gson.GsonBuilder
import java.io.File

class WorkoutStoreRepository(private val filesDir:File) : IWorkoutStoreRepository {
    override fun getWorkoutStore(): WorkoutStore {
        var workoutStore: WorkoutStore? = null

        val gson = GsonBuilder()
            .registerTypeAdapter(WorkoutComponent::class.java, WorkoutComponentAdapter())
            .registerTypeAdapter(Set::class.java, SetAdapter())
            .create()

        // Assuming you have a consistent filename pattern or a single file
        val filename = "workout_store.json"
        val file = File(filesDir, filename)
        if (file.exists()) {
            val jsonString = file.readText()
            workoutStore = gson.fromJson(jsonString, WorkoutStore::class.java)
        }

        Log.d("VALUE",workoutStore.toString());
        return workoutStore ?: WorkoutStore(emptyList())  // Return the result or a default value
    }

    override fun saveWorkoutStore(workoutStore: WorkoutStore) {
        val gson = GsonBuilder()
            .registerTypeAdapter(Exercise::class.java, WorkoutComponentAdapter())
            .registerTypeAdapter(ExerciseGroup::class.java, WorkoutComponentAdapter())
            .registerTypeAdapter(WeightSet::class.java, SetAdapter())
            .registerTypeAdapter(BodyWeightSet::class.java, SetAdapter())
            .registerTypeAdapter(TimedDurationSet::class.java, SetAdapter())
            .registerTypeAdapter(EnduranceSet::class.java, SetAdapter())
            .create()

        val jsonString = gson.toJson(workoutStore)
        val filename = "workout_store.json"  // Assuming a single file for the workout store
        val file = File(filesDir, filename)
        Log.d("JSON",jsonString);
        file.writeText(jsonString)  // Write the JSON string to the file
    }

    override fun saveWorkoutStoreFromJson(workoutStoreJson: String) {
        val filename = "workout_store.json"  // Assuming a single file for the workout store
        val file = File(filesDir, filename)
        file.writeText(workoutStoreJson)  // Write the JSON string to the file
    }
}