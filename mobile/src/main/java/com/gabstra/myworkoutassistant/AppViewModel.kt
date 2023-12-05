package com.gabstra.myworkoutassistant

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent

sealed class ScreenData(val route: String) {
    companion object {
        const val WORKOUTS_ROUTE = "Workouts"
        const val NEW_WORKOUT_ROUTE = "NewWorkout"
        const val EDIT_WORKOUT_ROUTE = "EditWorkout"
        const val WORKOUT_DETAIL_ROUTE = "WorkoutDetail"
        const val EXERCISE_GROUP_DETAIL_ROUTE = "ExerciseGroupDetail"
        const val EXERCISE_DETAIL_ROUTE = "ExerciseDetail"
        const val NEW_EXERCISE_GROUP_ROUTE = "NewExerciseGroup"
        const val EDIT_EXERCISE_GROUP_ROUTE = "EditExerciseGroup"
        const val NEW_EXERCISE_ROUTE = "NewExercise"
        const val EDIT_EXERCISE_ROUTE = "EditExercise"
        const val NEW_SET_ROUTE = "NewExercise"
        const val EDIT_SET_ROUTE = "EditExercise"
    }

    object Workouts : ScreenData(WORKOUTS_ROUTE)
    object NewWorkout : ScreenData(NEW_WORKOUT_ROUTE)
    data class EditWorkout(val selectedWorkout: Workout) : ScreenData(EDIT_WORKOUT_ROUTE)
    data class WorkoutDetail(val selectedWorkout: Workout) : ScreenData(WORKOUT_DETAIL_ROUTE)
    data class ExerciseGroupDetail(val selectedWorkout: Workout, val selectedExerciseGroup: ExerciseGroup, val parentExerciseGroup: ExerciseGroup?) : ScreenData(EXERCISE_GROUP_DETAIL_ROUTE)
    data class ExerciseDetail(val selectedWorkout: Workout, val selectedExercise: Exercise, val parentExerciseGroup: ExerciseGroup?) : ScreenData(EXERCISE_DETAIL_ROUTE)
    data class NewExerciseGroup(val selectedWorkout: Workout, val parentExerciseGroup: ExerciseGroup?) : ScreenData(NEW_EXERCISE_GROUP_ROUTE)
    data class EditExerciseGroup(val selectedWorkout: Workout, val selectedExerciseGroup: ExerciseGroup) : ScreenData(EDIT_EXERCISE_GROUP_ROUTE)
    data class NewExercise(val selectedWorkout: Workout, val parentExerciseGroup: ExerciseGroup?) : ScreenData(NEW_EXERCISE_ROUTE)
    data class EditExercise(val selectedWorkout: Workout, val selectedExercise: Exercise) : ScreenData(EDIT_EXERCISE_ROUTE)

    data class NewSet(val selectedWorkout: Workout, val parentExercise: Exercise) : ScreenData(NEW_SET_ROUTE)
    data class EditSet(val selectedWorkout: Workout, val selectedSet: Set, val parentExercise: Exercise) : ScreenData(EDIT_SET_ROUTE)
}


class AppViewModel() : ViewModel() {

    private var screenDataStack = mutableListOf<ScreenData>(ScreenData.Workouts)

    // CurrentScreenData as the top of the stack
    var currentScreenData: ScreenData
        get() = screenDataStack.lastOrNull() ?: ScreenData.Workouts
        private set(value) {
            screenDataStack.add(value)
        }

    fun setScreenData(screenData: ScreenData) {
        currentScreenData = screenData
    }

    // Go back to the previous screen
    fun goBack() {
        if (screenDataStack.size > 1) {
            screenDataStack.removeAt(screenDataStack.size - 1)
        }
    }

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

    fun updateWorkoutComponents(parentWorkout: Workout, oldWorkoutComponent: WorkoutComponent, updatedWorkoutComponent: WorkoutComponent) {
        workouts = workouts.map { workout ->
            if (workout == parentWorkout) {
                workout.copy(workoutComponents = updateWorkoutComponentsRecursively(workout.workoutComponents, oldWorkoutComponent, updatedWorkoutComponent))
            } else {
                workout
            }
        }
    }

    private fun updateWorkoutComponentsRecursively(components: List<WorkoutComponent>, oldComponent: WorkoutComponent, updatedComponent: WorkoutComponent): List<WorkoutComponent> {
        return components.map { component ->
            when (component) {
                oldComponent -> updatedComponent
                is ExerciseGroup -> component.copy(workoutComponents = updateWorkoutComponentsRecursively(component.workoutComponents, oldComponent, updatedComponent))
                else -> component
            }
        }
    }


    fun updateExercise(parentWorkout: Workout, parentExerciseGroup: ExerciseGroup, oldSet: Set, updatedSet: Set) {
        workouts = workouts.map { workout ->
            if (workout == parentWorkout) {
                workout.copy(
                    exerciseGroups = workout.exerciseGroups.map { exerciseGroup ->
                        if (exerciseGroup == parentExerciseGroup) {
                            exerciseGroup.copy(
                                exercises = exerciseGroup.exercises.map { exercise ->
                                    if (exercise == oldSet) updatedSet else exercise
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

    fun addWorkoutComponent(workout: Workout, newWorkoutComponent: WorkoutComponent) {
        workouts = workouts.map { it ->
            if (it == workout) {
                it.copy(workoutComponents = it.workoutComponents + newWorkoutComponent)
            } else {
                it
            }
        }
    }

    fun addWorkoutComponentToExerciseGroup(workout: Workout, exerciseGroup: ExerciseGroup, newWorkoutComponent: WorkoutComponent) {
        workouts = workouts.map { it ->
            if (it == workout) {
                it.copy(workoutComponents = addWorkoutComponentsRecursively(it.workoutComponents, exerciseGroup, newWorkoutComponent))
            } else {
                it
            }
        }
    }

    private fun addWorkoutComponentsRecursively(components: List<WorkoutComponent>, parentWorkoutComponent: WorkoutComponent, newWorkoutComponent: WorkoutComponent): List<WorkoutComponent> {
        return components.map { component ->
            when (component) {
                is ExerciseGroup ->
                {
                    if(component == parentWorkoutComponent) {
                        component.copy(workoutComponents = component.workoutComponents + newWorkoutComponent)
                    }else{
                        component.copy(workoutComponents = addWorkoutComponentsRecursively(component.workoutComponents, parentWorkoutComponent, newWorkoutComponent))
                    }
                }
                else -> component
        }
    }

    fun addNewExercise(parentWorkout: Workout, exerciseGroup: ExerciseGroup, newSet: Set) {
        workouts = workouts.map { workout ->
            if (workout == parentWorkout) {
                workout.copy(
                    exerciseGroups = workout.exerciseGroups.map { it ->
                        if (it == exerciseGroup) {
                            it.copy(exercises = it.exercises + newSet)
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

    fun deleteExercise(parentWorkout: Workout, exerciseGroup: ExerciseGroup, setToDelete: Set) {
        workouts = workouts.map { workout ->
            if (workout == parentWorkout) {  // Direct object comparison
                workout.copy(
                    exerciseGroups = workout.exerciseGroups.map { exerciseGroup ->
                        if (exerciseGroup == exerciseGroup) {  // Direct object comparison
                            exerciseGroup.copy(
                                exercises = exerciseGroup.exercises.filter { it != setToDelete }  // Direct object comparison
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
