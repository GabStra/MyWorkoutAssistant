package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.ExerciseGroup
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent

class WorkoutManager {
    companion object {
        fun updateWorkout(workouts: List<Workout>, oldWorkout: Workout, updatedWorkout: Workout) : List<Workout> {
            return workouts.map { workout ->
                if (workout == oldWorkout) updatedWorkout else workout
            }
        }

        fun updateWorkoutComponent(workouts: List<Workout>,parentWorkout: Workout, oldWorkoutComponent: WorkoutComponent, updatedWorkoutComponent: WorkoutComponent): List<Workout> {
            return workouts.map { workout ->
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

        fun addWorkoutComponent(workouts: List<Workout>, workout: Workout, newWorkoutComponent: WorkoutComponent): List<Workout>  {
            return workouts.map { it ->
                if (it == workout) {
                    it.copy(workoutComponents = it.workoutComponents + newWorkoutComponent)
                } else {
                    it
                }
            }
        }

        fun addWorkoutComponentToExerciseGroup(workouts: List<Workout>, workout: Workout, exerciseGroup: ExerciseGroup, newWorkoutComponent: WorkoutComponent): List<Workout> {
            return workouts.map { it ->
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

        fun addSetToExercise(workouts: List<Workout>, workout: Workout, exercise: Exercise, newSet: com.gabstra.myworkoutassistant.shared.sets.Set, index: Int? = null): List<Workout> {
            return workouts.map { currentWorkout ->
                if (currentWorkout == workout) {
                    currentWorkout.copy(workoutComponents = addSetToExerciseRecursively(currentWorkout.workoutComponents, exercise, newSet, index))
                } else {
                    currentWorkout
                }
            }
        }


        fun addSetToExerciseRecursively(components: List<WorkoutComponent>, parentExercise: Exercise, newSet: com.gabstra.myworkoutassistant.shared.sets.Set, index: Int? = null): List<WorkoutComponent> {
            return components.map { component ->
                when (component) {
                    is Exercise -> {
                        if (component == parentExercise) {
                            val mutableSets = component.sets.toMutableList()
                            if (index != null && index in mutableSets.indices) {
                                mutableSets.add(index, newSet)
                            } else {
                                mutableSets.add(newSet) // Add at the end if index is null or out of bounds
                            }
                            component.copy(sets = mutableSets.toList())
                        } else {
                            component
                        }
                    }
                    is ExerciseGroup -> {
                        component.copy(
                            workoutComponents = addSetToExerciseRecursively(
                                component.workoutComponents,
                                parentExercise,
                                newSet,
                                index
                            )
                        )
                    }
                }
            }
        }


        fun updateSetInExercise(workouts: List<Workout>, workout: Workout, exercise: Exercise, oldSet: com.gabstra.myworkoutassistant.shared.sets.Set, updatedSet: com.gabstra.myworkoutassistant.shared.sets.Set) : List<Workout> {
            return workouts.map { it ->
                if (it == workout) {
                    it.copy(workoutComponents = updateSetInExerciseRecursively(it.workoutComponents, exercise, oldSet, updatedSet))
                } else {
                    it
                }
            }
        }

        fun updateSetInExerciseRecursively(components: List<WorkoutComponent>, parentExercise: Exercise, oldSet: com.gabstra.myworkoutassistant.shared.sets.Set, updatedSet: com.gabstra.myworkoutassistant.shared.sets.Set): List<WorkoutComponent> {
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
                }
            }
        }

        private fun updateSet(sets: List<com.gabstra.myworkoutassistant.shared.sets.Set>, oldSet: com.gabstra.myworkoutassistant.shared.sets.Set, updatedSet: com.gabstra.myworkoutassistant.shared.sets.Set): List<com.gabstra.myworkoutassistant.shared.sets.Set> {
            return sets.map { set ->
                if(set === oldSet) {
                    updatedSet
                }else{
                    set
                }
            }
        }

        fun deleteWorkoutComponent(workouts: List<Workout>, workout: Workout, workoutComponentToDelete: WorkoutComponent) : List<Workout> {
            return workouts.map {
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

        fun deleteSet(workouts: List<Workout>, workout: Workout, exercise: Exercise, setToDelete: com.gabstra.myworkoutassistant.shared.sets.Set) : List<Workout> {
            return workouts.map {
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

        private fun deleteSetRecursively(components: List<WorkoutComponent>, exercise: Exercise, setToDelete: com.gabstra.myworkoutassistant.shared.sets.Set): List<WorkoutComponent> {
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
                }
            }
        }

        fun getAllExercisesFromWorkout(workout: Workout): List<Exercise> {
            val sets = mutableListOf<Exercise>()

            for(workoutComponent in workout.workoutComponents){
                when(workoutComponent){
                    is Exercise -> sets.add(workoutComponent)
                    is ExerciseGroup -> sets.addAll(getAllExercisesFromExerciseGroup(workoutComponent))
                }
            }

            return sets.toList()
        }

        fun getAllExercisesFromExerciseGroup(exerciseGroup: ExerciseGroup): List<Exercise>{
            val sets = mutableListOf<Exercise>()

            for(workoutComponent in exerciseGroup.workoutComponents){
                when(workoutComponent){
                    is Exercise -> sets.add(workoutComponent)
                    is ExerciseGroup -> sets.addAll(getAllExercisesFromExerciseGroup(workoutComponent))
                }
            }

            return sets.toList()
        }

    }
}