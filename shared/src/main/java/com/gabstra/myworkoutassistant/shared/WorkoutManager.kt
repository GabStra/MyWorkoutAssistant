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
            val newVersionId = UUID.randomUUID()
            val newVersion = updatedWorkout.copy(
                id = newVersionId,
                creationDate = LocalDate.now(),
                previousVersionId = oldWorkout.id,
                nextVersionId = null,
                isActive = true,
                globalId = oldWorkout.globalId
            )

            val updatedOldWorkout = oldWorkout.copy(isActive = false, nextVersionId = newVersionId)

            return workouts.map { workout ->
                if (workout == oldWorkout) updatedOldWorkout else workout
            } + newVersion
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
                    exercise.copy(sets = mutableSets.toList(), requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds ?: emptyList())
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
                    exercise.copy(sets = emptyList(), requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds ?: emptyList())
                } else {
                    if(component is Superset){
                        component.copy(exercises = removeSetsFromExerciseRecursively(component.exercises, parentExercise) as List<Exercise>)
                    }else{
                        component
                    }
                }
            }
        }

        /**
         * Merges plan sets with set history while respecting each set's reapply policy.
         * Executed history order is authoritative for any set that appears in history so
         * in-session inserted sets keep their position. Programmed-only sets that have no
         * matching history are appended afterward in original order.
         */
        fun mergeExerciseSetsFromHistory(originalSets: List<Set>, setHistories: List<SetHistory>): List<Set> {
            val orderedSetHistories = setHistories
                .sortedBy { it.order.toInt() }
                .distinctBy { it.setId }
            val originalSetsById = originalSets.associateBy { it.id }
            val mergedSets = orderedSetHistories.map { setHistory ->
                originalSetsById[setHistory.setId]?.let { set ->
                    applySetHistoryToProgrammedSet(set, setHistory)
                } ?: getNewSetFromSetHistory(setHistory)
            }
            val historicalSetIds = orderedSetHistories.map { it.setId }.toSet()
            val originalOnlySets = originalSets.filter { it.id !in historicalSetIds }
            return mergedSets + originalOnlySets
        }

        /**
         * Replaces an exercise's sets list in the component tree (recurse into Superset).
         */
        fun replaceSetsInExerciseRecursively(components: List<WorkoutComponent>, parentExercise: Exercise, newSets: List<Set>): List<WorkoutComponent> {
            return components.map { component ->
                if (component.id == parentExercise.id) {
                    val exercise = component as Exercise
                    exercise.copy(sets = newSets, requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds ?: emptyList())
                } else {
                    if (component is Superset) {
                        component.copy(exercises = replaceSetsInExerciseRecursively(component.exercises, parentExercise, newSets) as List<Exercise>)
                    } else {
                        component
                    }
                }
            }
        }

        fun updateSetInExerciseRecursively(components: List<WorkoutComponent>, parentExercise: Exercise, oldSet: Set, updatedSet: Set): List<WorkoutComponent> {
            return components.map { component ->
                if(component == parentExercise) {
                    val exercise = component as Exercise
                    exercise.copy(sets = updateSet(component.sets,oldSet,updatedSet), requiredAccessoryEquipmentIds = exercise.requiredAccessoryEquipmentIds ?: emptyList())
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

        fun moveWorkoutComponents(sourceWorkouts: List<Workout>, sourceWorkout: Workout, componentsToMove: List<WorkoutComponent>, targetWorkout: Workout): List<Workout> {
            // Remove from source
            val updatedSourceWorkouts = sourceWorkouts.map { workout ->
                if (workout.id == sourceWorkout.id) {
                    workout.copy(workoutComponents = workout.workoutComponents.filter { it !in componentsToMove })
                } else {
                    workout
                }
            }
            
            // Add to target - find by globalId and isActive to handle versioned workouts correctly
            return updatedSourceWorkouts.map { workout ->
                if (workout.globalId == targetWorkout.globalId && workout.isActive) {
                    workout.copy(workoutComponents = workout.workoutComponents + componentsToMove)
                } else {
                    workout
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
