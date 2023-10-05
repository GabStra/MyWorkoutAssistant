package com.gabstra.myworkoutassistant

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import com.gabstra.myworkoutassistant.shared.Exercise
import com.gabstra.myworkoutassistant.shared.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.Workout

enum class Screen(val route: String) {
    Workouts("Workouts"),
    NewWorkout("NewWorkout"),
    EditWorkout("NewWorkout/{workoutId}"),
    WorkoutDetail("WorkoutDetail/{workoutId}"),
    ExerciseGroupDetail("ExerciseGroupDetail/{workoutId}/{exerciseGroupId}"),
    NewExerciseGroup("NewExerciseGroup/{workoutId}"),
    EditExerciseGroup("EditExerciseGroup/{workoutId}/{exerciseGroupId}"),
    NewExercise("NewExercise/{workoutId}/{exerciseGroupId}"),
    EditExercise("EditExercise/{workoutId}/{exerciseGroupId}/{exerciseId}");

    companion object {
        fun getRoute(screen: Screen, workoutId: Int): String {
            return screen.route
                .replace("{workoutId}", workoutId.toString())
        }
        fun getRoute(screen: Screen, workoutId: Int, exerciseGroupId: Int): String {
            return screen.route
                .replace("{workoutId}", workoutId.toString())
                .replace("{exerciseGroupId}", exerciseGroupId.toString())
        }
        fun getRoute(screen: Screen, workoutId: Int, exerciseGroupId: Int, exerciseId: Int): String {
            return screen.route
                .replace("{workoutId}", workoutId.toString())
                .replace("{exerciseGroupId}", exerciseGroupId.toString())
                .replace("{exerciseId}", exerciseId.toString())
        }
    }
}

class AppViewModel() : ViewModel() {
    var workouts by mutableStateOf(emptyList<Workout>())
        private set

    fun updateWorkouts(newWorkouts: List<Workout>) {
        workouts = newWorkouts
    }

    fun updateWorkout(oldWorkout: Workout, updatedWorkout: Workout) {
        workouts = workouts.map { workout ->
            if (workout == oldWorkout) updatedWorkout else workout
        }
    }

    fun updateExerciseGroup(parentWorkout: Workout, oldExerciseGroup: ExerciseGroup, updatedExerciseGroup: ExerciseGroup) {
        workouts = workouts.map { workout ->
            if (workout == parentWorkout) {
                workout.copy(
                    exerciseGroups = workout.exerciseGroups.map { exerciseGroup ->
                        if (exerciseGroup == oldExerciseGroup) updatedExerciseGroup else exerciseGroup
                    }
                )
            } else {
                workout
            }
        }
    }

    fun updateExercise(parentWorkout: Workout, parentExerciseGroup: ExerciseGroup, oldExercise: Exercise, updatedExercise: Exercise) {
        workouts = workouts.map { workout ->
            if (workout == parentWorkout) {
                workout.copy(
                    exerciseGroups = workout.exerciseGroups.map { exerciseGroup ->
                        if (exerciseGroup == parentExerciseGroup) {
                            exerciseGroup.copy(
                                exercises = exerciseGroup.exercises.map { exercise ->
                                    if (exercise == oldExercise) updatedExercise else exercise
                                }
                            )
                        } else {
                            exerciseGroup
                        }
                    }
                )
            } else {
                workout
            }
        }
    }

    fun addNewWorkout(newWorkout: Workout) {
        workouts = workouts + newWorkout
    }

    fun addNewExerciseGroup(workout: Workout, newExerciseGroup: ExerciseGroup) {
        workouts = workouts.map { it ->
            if (it == workout) {
                it.copy(exerciseGroups = it.exerciseGroups + newExerciseGroup)
            } else {
                it
            }
        }
    }

    fun addNewExercise(parentWorkout: Workout, exerciseGroup: ExerciseGroup, newExercise: Exercise) {
        workouts = workouts.map { workout ->
            if (workout == parentWorkout) {
                workout.copy(
                    exerciseGroups = workout.exerciseGroups.map { it ->
                        if (it == exerciseGroup) {
                            it.copy(exercises = it.exercises + newExercise)
                        } else {
                            it
                        }
                    }
                )
            } else {
                workout
            }
        }
    }

    fun deleteWorkout(workoutToDelete: Workout) {
        workouts = workouts.filter { it != workoutToDelete }  // Direct object comparison
    }

    fun deleteExerciseGroup(parentWorkout: Workout, exerciseGroupToDelete: ExerciseGroup) {
        workouts = workouts.map { workout ->
            if (workout == parentWorkout) {  // Direct object comparison
                workout.copy(
                    exerciseGroups = workout.exerciseGroups.filter { it != exerciseGroupToDelete }  // Direct object comparison
                )
            } else {
                workout
            }
        }
    }

    fun deleteExercise(parentWorkout: Workout,exerciseGroup: ExerciseGroup, exerciseToDelete: Exercise) {
        workouts = workouts.map { workout ->
            if (workout == parentWorkout) {  // Direct object comparison
                workout.copy(
                    exerciseGroups = workout.exerciseGroups.map { exerciseGroup ->
                        if (exerciseGroup == exerciseGroup) {  // Direct object comparison
                            exerciseGroup.copy(
                                exercises = exerciseGroup.exercises.filter { it != exerciseToDelete }  // Direct object comparison
                            )
                        } else {
                            exerciseGroup
                        }
                    }
                )
            } else {
                workout
            }
        }
    }
}
