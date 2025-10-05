package com.gabstra.myworkoutassistant.shared

import com.gabstra.myworkoutassistant.shared.sets.BodyWeightSet
import com.gabstra.myworkoutassistant.shared.sets.EnduranceSet
import com.gabstra.myworkoutassistant.shared.sets.RestSet
import com.gabstra.myworkoutassistant.shared.sets.Set
import com.gabstra.myworkoutassistant.shared.sets.TimedDurationSet
import com.gabstra.myworkoutassistant.shared.sets.WeightSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.workoutcomponents.WorkoutComponent
import java.time.LocalDate
import java.util.UUID

class WorkoutManager {
    companion object {
        fun updateWorkoutOld(workouts: List<Workout>, oldWorkout: Workout, updatedWorkout: Workout) : List<Workout> {
            return workouts.map { workout ->
                if (workout == oldWorkout) updatedWorkout else workout
            }
        }

        fun updateWorkout(workouts: List<Workout>, oldWorkout: Workout, updatedWorkout: Workout): List<Workout> {
            val newVersion = updatedWorkout.copy(
                id = UUID.randomUUID(), // Genera un nuovo ID per la nuova versione
                creationDate = LocalDate.now(), // Imposta la data corrente
                previousVersionId = oldWorkout.id // Imposta il riferimento alla versione precedente
            )

            val updatedOldWorkout = updatedWorkout.copy(isActive = false, nextVersionId = newVersion.id)

            return workouts.map { workout ->
                if (workout == oldWorkout) updatedOldWorkout else workout
            } + newVersion
        }

/*        fun updateWorkoutComponent(workouts: List<Workout>, parentWorkout: Workout, oldWorkoutComponent: WorkoutComponent, updatedWorkoutComponent: WorkoutComponent): List<Workout> {
            val updatedComponents = updateWorkoutComponentsRecursively(parentWorkout.workoutComponents, oldWorkoutComponent, updatedWorkoutComponent)
            val updatedWorkout = parentWorkout.copy(workoutComponents = updatedComponents)
            return updateWorkout(workouts, parentWorkout, updatedWorkout)
        }*/

        fun updateWorkoutComponentOld(workouts: List<Workout>, parentWorkout: Workout, oldWorkoutComponent: WorkoutComponent, updatedWorkoutComponent: WorkoutComponent): List<Workout> {
            val updatedComponents = updateWorkoutComponentsRecursively(parentWorkout.workoutComponents, oldWorkoutComponent, updatedWorkoutComponent)
            val updatedWorkout = parentWorkout.copy(workoutComponents = updatedComponents)
            return updateWorkoutOld(workouts, parentWorkout, updatedWorkout)
        }

        fun updateWorkoutComponentsRecursively(workoutComponents: List<WorkoutComponent>, oldComponent: WorkoutComponent, updatedComponent: WorkoutComponent): List<WorkoutComponent> {
            return workoutComponents.map { component ->
                if (component == oldComponent) {
                    updatedComponent
                } else {
                    if(updatedComponent is Exercise && component is Superset){
                        component.copy(exercises = updateWorkoutComponentsRecursively(component.exercises, oldComponent as Exercise,
                            updatedComponent
                        ) as List<Exercise>)
                    }else{
                        component
                    }

                    /*
                    when (component) {
                        is ExerciseGroup -> component.copy(workoutComponents = updateWorkoutComponentsRecursively(component.workoutComponents, oldComponent, updatedComponent))
                        else -> component
                    }
                    */
                }
            }
        }

        fun addWorkoutComponent(workouts: List<Workout>, workout: Workout, newWorkoutComponent: WorkoutComponent): List<Workout> {
            val updatedComponents = workout.workoutComponents + newWorkoutComponent
            val updatedWorkout = workout.copy(workoutComponents = updatedComponents)
            return updateWorkoutOld(workouts, workout, updatedWorkout)
        }

        /*
        fun addWorkoutComponentToExerciseGroup(workouts: List<Workout>, workout: Workout, exerciseGroup: ExerciseGroup, newWorkoutComponent: WorkoutComponent): List<Workout> {
            // Crea una nuova lista di componenti del workout con il nuovo componente aggiunto all'ExerciseGroup
            val updatedComponents = addWorkoutComponentsRecursively(workout.workoutComponents, exerciseGroup, newWorkoutComponent)

            // Crea un nuovo workout con i componenti aggiornati
            val updatedWorkout = workout.copy(workoutComponents = updatedComponents)

            // Utilizza la funzione updateWorkout per creare una nuova versione del workout
            return updateWorkout(workouts, workout, updatedWorkout)
        }*/

        /*
      // Funzione ricorsiva per aggiungere componenti ai gruppi di esercizi
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
        }*/

        fun addSetToExercise(workouts: List<Workout>, workout: Workout, exercise: Exercise, newSet: Set, index: UInt? = null): List<Workout> {
            return workouts.map { currentWorkout ->
                if (currentWorkout == workout) {
                    currentWorkout.copy(workoutComponents = addSetToExerciseRecursively(currentWorkout.workoutComponents, exercise, newSet, index))
                } else {
                    currentWorkout
                }
            }
        }

        fun addSetToExerciseRecursively(components: List<WorkoutComponent>, parentExercise: Exercise, newSet: Set, index: UInt? = null): List<WorkoutComponent> {
            return components.map { component ->
                if (component.id == parentExercise.id) {
                    val exercise = component as Exercise
                    val mutableSets = component.sets.toMutableList()
                    if (index != null && index.toInt() in mutableSets.indices) {
                        mutableSets.add(index.toInt(), newSet)
                    } else {
                        mutableSets.add(newSet) // Add at the end if index is null or out of bounds
                    }
                    exercise.copy(sets = mutableSets.toList())
                } else {
                    if(component is Superset){
                        component.copy(exercises = addSetToExerciseRecursively(component.exercises, parentExercise, newSet, index) as List<Exercise>)
                    }else{
                        component
                    }
                }
            }
        }

        fun removeSetsFromExerciseRecursively(components: List<WorkoutComponent>, parentExercise: Exercise): List<WorkoutComponent> {
            return components.map { component ->
                if (component.id == parentExercise.id) {
                    val exercise = component as Exercise
                    exercise.copy(sets = emptyList())
                } else {
                    if(component is Superset){
                        component.copy(exercises = removeSetsFromExerciseRecursively(component.exercises, parentExercise) as List<Exercise>)
                    }else{
                        component
                    }
                }
            }
        }

        fun updateSetInExercise(workouts: List<Workout>, workout: Workout, exercise: Exercise, oldSet: Set, updatedSet: Set) : List<Workout> {
            return workouts.map { it ->
                if (it == workout) {
                    it.copy(workoutComponents = updateSetInExerciseRecursively(it.workoutComponents, exercise, oldSet, updatedSet))
                } else {
                    it
                }
            }
        }

        fun updateSetInExerciseRecursively(components: List<WorkoutComponent>, parentExercise: Exercise, oldSet: Set, updatedSet: Set): List<WorkoutComponent> {
            return components.map { component ->
                if(component == parentExercise) {
                    val exercise = component as Exercise
                    exercise.copy(sets = updateSet(component.sets,oldSet,updatedSet))
                }else{
                    if(component is Superset){
                        component.copy(exercises = updateSetInExerciseRecursively(component.exercises, parentExercise, oldSet, updatedSet) as List<Exercise>)
                    }else{
                        component
                    }
                }
            }
        }

        private fun updateSet(sets: List<Set>, oldSet: Set, updatedSet: Set): List<Set> {
            return sets.map { set ->
                if(set.id == oldSet.id) {
                    updatedSet
                }else{
                    set
                }
            }
        }

        fun deleteSet(workouts: List<Workout>, workout: Workout, exercise: Exercise, setToDelete: Set) : List<Workout> {
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

        private fun deleteSetRecursively(components: List<WorkoutComponent>, exercise: Exercise, setToDelete: Set): List<WorkoutComponent> {
            return components.map { component ->
                if (component == exercise) {
                    val selectedExercise = component as Exercise
                    selectedExercise.copy(
                        sets = component.sets.filter { set -> set != setToDelete }
                    )
                } else {
                    if(component is Superset){
                        component.copy(exercises = deleteSetRecursively(component.exercises, exercise, setToDelete) as List<Exercise>)
                    }else{
                        component
                    }
                }
            }
        }

        fun moveWorkoutComponents(sourceWorkouts: List<Workout>, sourceWorkout: Workout, componentsToMove: List<WorkoutComponent>, targetWorkout: Workout): List<Workout> {
            // Remove from source
            val updatedSourceWorkouts = sourceWorkouts.map { workout ->
                if (workout == sourceWorkout) {
                    workout.copy(workoutComponents = workout.workoutComponents.filter { it !in componentsToMove })
                } else {
                    workout
                }
            }
            
            // Add to target
            return updatedSourceWorkouts.map { workout ->
                if (workout == targetWorkout) {
                    workout.copy(workoutComponents = workout.workoutComponents + componentsToMove)
                } else {
                    workout
                }
            }
        }

        fun deleteWorkoutComponent(workouts: List<Workout>, workout: Workout, workoutComponentToDelete: WorkoutComponent) : List<Workout> {
            return workouts.map {
                if (it == workout) {
                    if(workoutComponentToDelete in it.workoutComponents){
                        it.copy(
                            workoutComponents = it.workoutComponents.filter { workoutComponent ->
                                workoutComponent != workoutComponentToDelete
                             }.map {  workoutComponent ->
                                if(workoutComponent is Superset){
                                    workoutComponent.copy(exercises = workoutComponent.exercises.filter { exercise -> exercise != workoutComponentToDelete } as List<Exercise>)
                                }else{
                                    workoutComponent
                                }
                            }
                        )
                    }else{
                        it
                    }
                } else {
                    it
                }
            }
        }

        fun cloneWorkoutComponent(workoutComponent: WorkoutComponent): WorkoutComponent {
            return when (workoutComponent) {
                is Exercise -> {
                    val newSets = workoutComponent.sets.map {
                        when (it){
                            is BodyWeightSet -> it.copy(id = UUID.randomUUID())
                            is WeightSet -> it.copy(id = UUID.randomUUID())
                            is EnduranceSet -> it.copy(id = UUID.randomUUID())
                            is TimedDurationSet -> it.copy(id = UUID.randomUUID())
                            is RestSet -> it.copy(id = UUID.randomUUID())
                        }
                    }
                    workoutComponent.copy(name = workoutComponent.name + " (copy)", id = UUID.randomUUID(), sets = newSets)
                }
                is Rest -> {
                    workoutComponent.copy(id = UUID.randomUUID())
                }
                is Superset -> {
                    val newExercises = workoutComponent.exercises.map { cloneWorkoutComponent(it) as Exercise }
                    workoutComponent.copy(id = UUID.randomUUID(), exercises = newExercises)
                }
                else -> throw IllegalArgumentException("Unknown workout component type")
            }
        }
    }
}
