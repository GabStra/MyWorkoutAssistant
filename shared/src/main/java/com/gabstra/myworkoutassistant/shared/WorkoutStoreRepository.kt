package com.gabstra.myworkoutassistant.shared

import java.io.File
import java.util.UUID

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

        val result = workoutStore ?: WorkoutStore(emptyList(), emptyList(), emptyList(), emptyList(), null, 0, 0.0, 0.0)
        // WorkoutStoreAdapter ensures lists are never null, so we can directly migrate
        return migrateWorkoutStore(result)
    }
    
    private fun migrateWorkoutStore(workoutStore: WorkoutStore): WorkoutStore {
        val workoutPlans = workoutStore.workoutPlans
        val workouts = workoutStore.workouts
        
        // If workoutPlans is empty, create default "Unassigned" plan and assign all workouts to it
        if (workoutPlans.isEmpty() && workouts.isNotEmpty()) {
            val unassignedPlanId = UUID.randomUUID()
            val unassignedPlan = WorkoutPlan(
                id = unassignedPlanId,
                name = "Unassigned",
                workoutIds = workouts.map { it.id },
                order = 0
            )
            
            // Update all workouts to have the workoutPlanId
            val migratedWorkouts = workouts.map { workout ->
                if (workout.workoutPlanId == null) {
                    workout.copy(workoutPlanId = unassignedPlanId)
                } else {
                    workout
                }
            }
            
            return workoutStore.copy(
                workouts = migratedWorkouts,
                workoutPlans = listOf(unassignedPlan)
            )
        }
        
        // If workouts exist but some don't have workoutPlanId, assign them to Unassigned plan
        val workoutsWithoutPlan = workouts.filter { it.workoutPlanId == null }
        if (workoutsWithoutPlan.isNotEmpty()) {
            val unassignedPlan = workoutPlans.find { it.name == "Unassigned" }
            val unassignedPlanId = unassignedPlan?.id ?: UUID.randomUUID()
            
            val updatedPlans = if (unassignedPlan == null) {
                val newUnassignedPlan = WorkoutPlan(
                    id = unassignedPlanId,
                    name = "Unassigned",
                    workoutIds = workoutsWithoutPlan.map { it.id },
                    order = (workoutPlans.maxOfOrNull { it.order } ?: -1) + 1
                )
                workoutPlans + newUnassignedPlan
            } else {
                workoutPlans.map { plan ->
                    if (plan.id == unassignedPlanId) {
                        plan.copy(workoutIds = plan.workoutIds + workoutsWithoutPlan.map { it.id })
                    } else {
                        plan
                    }
                }
            }
            
            val migratedWorkouts = workouts.map { workout ->
                if (workout.workoutPlanId == null) {
                    workout.copy(workoutPlanId = unassignedPlanId)
                } else {
                    workout
                }
            }
            
            return workoutStore.copy(
                workouts = migratedWorkouts,
                workoutPlans = updatedPlans
            )
        }
        
        return workoutStore
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