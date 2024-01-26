package com.gabstra.myworkoutassistant

import android.util.Log
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.lifecycle.ViewModel
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.asStateFlow
import java.util.UUID

sealed class ScreenData() {
    class Workouts() : ScreenData()
    class Settings() : ScreenData()
    class NewWorkout() : ScreenData()
    class EditWorkout(val workoutId: UUID) : ScreenData()
    class WorkoutDetail(val workoutId: UUID) : ScreenData()
    class ExerciseGroupDetail(val workoutId: UUID, val selectedExerciseGroupId: UUID) : ScreenData()
    class ExerciseDetail(val workoutId: UUID, val selectedExerciseId: UUID) : ScreenData()
    class NewExerciseGroup(val workoutId: UUID, val parentExerciseGroupId: UUID?) : ScreenData()
    class EditExerciseGroup(val workoutId: UUID, val selectedExerciseGroupId: UUID) : ScreenData()
    class NewExercise(val workoutId: UUID, val parentExerciseGroupId: UUID?) : ScreenData()
    class EditExercise(val workoutId: UUID, val selectedExerciseId: UUID) : ScreenData()
    class NewSet(val workoutId: UUID, val parentExerciseId: UUID) : ScreenData()
    class EditSet(val workoutId: UUID, val selectedSet: Set, val parentExerciseId: UUID) : ScreenData()
}


class AppViewModel() : ViewModel() {
    private var screenDataStack = mutableListOf<ScreenData>(ScreenData.Workouts())

    // Convert currentScreenData to a MutableState
    var currentScreenData: ScreenData by mutableStateOf(screenDataStack.lastOrNull() ?: ScreenData.Workouts())
        private set

    fun setScreenData(screenData: ScreenData) {
        currentScreenData = screenData
        screenDataStack.add(screenData)
    }

    fun goBack(): Boolean {
        if (screenDataStack.size > 1) {
            screenDataStack.removeAt(screenDataStack.size - 1)
            currentScreenData = screenDataStack.last()
            return true
        } else if (screenDataStack.size == 1) {
            // Handle the case where stack size is 1
            // You can perform some action here if needed
            return false
        }
        return false
    }
    var workoutStore by mutableStateOf(WorkoutStore(
        workouts = emptyList(),
        polarDeviceId = null,
        birthDateYear = 0
    ))
        private set

    private val _workoutsFlow = MutableStateFlow(workoutStore.workouts)
    val workoutsFlow = _workoutsFlow.asStateFlow()

    var workouts: List<Workout>
        get() = workoutStore.workouts
        private set(value) {
            _workoutsFlow.value = value
            Log.d("AppViewModel", "WORKOUTS LOADED ${value.size}")
            workoutStore = workoutStore.copy(workouts = value)
        }

    fun updateWorkoutStore(newWorkoutStore: WorkoutStore) {
        workoutStore = newWorkoutStore
        _workoutsFlow.value = newWorkoutStore.workouts
    }

    fun updateWorkouts(newWorkouts: List<Workout>) {
        workouts = newWorkouts
    }

    fun updateWorkout(oldWorkout: Workout, updatedWorkout: Workout) {
        workouts = workouts.map { workout ->
            if (workout == oldWorkout) updatedWorkout else workout
        }
    }

    fun updateWorkoutComponent(parentWorkout: Workout, oldWorkoutComponent: WorkoutComponent, updatedWorkoutComponent: WorkoutComponent) {
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
            if(component == oldComponent) {
                updatedComponent
            } else{
                when (component) {
                    is ExerciseGroup -> component.copy(workoutComponents = updateWorkoutComponentsRecursively(component.workoutComponents, oldComponent, updatedComponent))
                    else -> component
                }
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
                is ExerciseGroup -> {
                    if (component == parentWorkoutComponent) {
                        component.copy(workoutComponents = component.workoutComponents + newWorkoutComponent)
                    } else {
                        component.copy(
                            workoutComponents = addWorkoutComponentsRecursively(
                                component.workoutComponents,
                                parentWorkoutComponent,
                                newWorkoutComponent
                            )
                        )
                    }
                }
                else -> component
            }
        }
    }

    fun addSetToExercise(workout: Workout, exercise: Exercise, newSet: Set) {
        workouts = workouts.map { it ->
            if (it == workout) {
                it.copy(workoutComponents = addSetToExerciseRecursively(it.workoutComponents, exercise, newSet))
            } else {
                it
            }
        }
    }

    private fun addSetToExerciseRecursively(components: List<WorkoutComponent>, parentExercise: Exercise, newSet: Set): List<WorkoutComponent> {
        return components.map { component ->
            when (component) {
                is Exercise ->
                    if(component == parentExercise) {
                        component.copy(sets = component.sets + newSet)
                    }else{
                        component
                    }
                is ExerciseGroup -> {
                    component.copy(
                        workoutComponents = addSetToExerciseRecursively(
                            component.workoutComponents,
                            parentExercise,
                            newSet
                        )
                    )
                }
                else -> component
            }
        }
    }

    fun updateSetInExercise(workout: Workout, exercise: Exercise, oldSet:Set,updatedSet: Set) {
        workouts = workouts.map { it ->
            if (it == workout) {
                it.copy(workoutComponents = updateSetInExerciseRecursively(it.workoutComponents, exercise, oldSet, updatedSet))
            } else {
                it
            }
        }
    }

    private fun updateSetInExerciseRecursively(components: List<WorkoutComponent>, parentExercise: Exercise, oldSet:Set,updatedSet: Set): List<WorkoutComponent> {
        return components.map { component ->
            when (component) {
                is Exercise ->
                    if(component == parentExercise) {
                        component.copy(sets = updateSet(component.sets,oldSet,updatedSet))
                    }else{
                        component
                    }
                is ExerciseGroup -> {
                    component.copy(
                        workoutComponents = updateSetInExerciseRecursively(
                            component.workoutComponents,
                            parentExercise,
                            oldSet,
                            updatedSet
                        )
                    )
                }
                else -> component
            }
        }
    }

    private fun updateSet(sets: List<Set>, oldSet: Set, updatedSet: Set): List<Set> {
        return sets.map { set ->
            if(set === oldSet) {
                updatedSet
            }else{
                set
            }
        }
    }

    fun deleteWorkout(workoutToDelete: Workout) {
        workouts = workouts.filter { it != workoutToDelete }  // Direct object comparison
    }

    fun deleteWorkoutComponent(workout: Workout, workoutComponentToDelete: WorkoutComponent) {
        workouts = workouts.map {
            if (it == workout) {
                if(workoutComponentToDelete in it.workoutComponents){
                    it.copy(
                        workoutComponents = it.workoutComponents.filter { workoutComponent -> workoutComponent != workoutComponentToDelete }  // Direct object comparison
                    )
                }else{
                    it.copy(
                        workoutComponents = deleteWorkoutComponentsRecursively(it.workoutComponents, workoutComponentToDelete)
                    )
                }
            } else {
                it
            }
        }
    }

    private fun deleteWorkoutComponentsRecursively(components: List<WorkoutComponent>, workoutComponentToDelete: WorkoutComponent): List<WorkoutComponent> {
        return components.map { component ->
            when (component) {
                is ExerciseGroup -> {
                    if (workoutComponentToDelete in component.workoutComponents) {
                        component.copy(
                            workoutComponents = component.workoutComponents.filter { workoutComponent -> workoutComponent != workoutComponentToDelete }
                        )
                    } else {
                        component.copy(
                            workoutComponents = deleteWorkoutComponentsRecursively(
                                component.workoutComponents,
                                workoutComponentToDelete
                            )
                        )
                    }
                }
                else -> component
            }
        }
    }

    fun deleteSet(workout: Workout, exercise: Exercise, setToDelete: Set) {
        workouts = workouts.map {
            if (it == workout) {
                workout.copy(
                    workoutComponents  = deleteSetRecursively(
                        it.workoutComponents,
                        exercise,
                        setToDelete
                    )
                )
            } else {
                workout
            }
        }
    }

    private fun deleteSetRecursively(components: List<WorkoutComponent>, exercise: Exercise, setToDelete: Set): List<WorkoutComponent> {
        return components.map { component ->
            when (component) {
                is Exercise -> {
                    if (component == exercise) {
                        component.copy(
                            sets = component.sets.filter { set -> set != setToDelete }
                        )
                    } else {
                        component
                    }
                }
                is ExerciseGroup -> {
                    component.copy(
                        workoutComponents = deleteSetRecursively(
                            component.workoutComponents,
                            exercise,
                            setToDelete
                        )
                    )
                }
                else -> component
            }
        }
    }
}
