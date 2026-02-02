package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.UNASSIGNED_PLAN_NAME
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.formatNumber
import com.gabstra.myworkoutassistant.shared.formatWeight
import com.gabstra.myworkoutassistant.shared.equipments.Barbell
import com.gabstra.myworkoutassistant.shared.equipments.BaseWeight
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbell
import com.gabstra.myworkoutassistant.shared.equipments.Dumbbells
import com.gabstra.myworkoutassistant.shared.equipments.EquipmentType
import com.gabstra.myworkoutassistant.shared.equipments.Machine
import com.gabstra.myworkoutassistant.shared.equipments.Plate
import com.gabstra.myworkoutassistant.shared.equipments.PlateLoadedCable
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import com.gabstra.myworkoutassistant.shared.equipments.WeightVest
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
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
import com.gabstra.myworkoutassistant.shared.utils.WarmupContext
import com.gabstra.myworkoutassistant.shared.utils.WarmupContextBuilder
import com.gabstra.myworkoutassistant.shared.utils.WarmupPlanner
import kotlin.math.roundToInt

fun buildWorkoutPlanMarkdown(workoutStore: WorkoutStore): String {
    val markdown = StringBuilder()
    
    markdown.append("# Workout Plan Export\n\n")
    markdown.append("This document contains equipment specifications and workout plan details.\n\n")
    
    // Equipment Section
    markdown.append("## Equipment\n\n")
    
    if (workoutStore.equipments.isEmpty()) {
        markdown.append("No equipment configured.\n\n")
    } else {
        workoutStore.equipments.forEachIndexed { index, equipment ->
            markdown.append("### ${index + 1}. ${equipment.name}\n\n")
            markdown.append("- **Type**: ${equipment.type.toDisplayText()}\n")
            
            when (equipment) {
                is Barbell -> {
                    markdown.append("- **Bar Weight**: ${formatNumber(equipment.barWeight)} kg\n")
                    if (equipment.availablePlates.isNotEmpty()) {
                        markdown.append("- **Available Plates**: ")
                        val platesStr = equipment.availablePlates
                            .sortedByDescending { it.weight }
                            .joinToString(", ") { "${formatNumber(it.weight)} kg" }
                        markdown.append(platesStr).append("\n")
                    }
                }
                
                is Dumbbells -> {
                    if (equipment.availableDumbbells.isNotEmpty()) {
                        markdown.append("- **Available Dumbbells**: ")
                        val dumbbellsStr = equipment.availableDumbbells
                            .sortedByDescending { it.weight }
                            .joinToString(", ") { "${formatNumber(it.weight)} kg each" }
                        markdown.append(dumbbellsStr).append("\n")
                    }
                    if (equipment.extraWeights.isNotEmpty()) {
                        markdown.append("- **Extra Weights**: ")
                        val extraStr = equipment.extraWeights
                            .sortedByDescending { it.weight }
                            .joinToString(", ") { "${formatNumber(it.weight)} kg" }
                        markdown.append(extraStr).append("\n")
                    }
                }
                
                is Dumbbell -> {
                    if (equipment.availableDumbbells.isNotEmpty()) {
                        markdown.append("- **Available Dumbbells**: ")
                        val dumbbellsStr = equipment.availableDumbbells
                            .sortedByDescending { it.weight }
                            .joinToString(", ") { "${formatNumber(it.weight)} kg each" }
                        markdown.append(dumbbellsStr).append("\n")
                    }
                    if (equipment.extraWeights.isNotEmpty()) {
                        markdown.append("- **Extra Weights**: ")
                        val extraStr = equipment.extraWeights
                            .sortedByDescending { it.weight }
                            .joinToString(", ") { "${formatNumber(it.weight)} kg" }
                        markdown.append(extraStr).append("\n")
                    }
                }
                
                is Machine -> {
                    if (equipment.availableWeights.isNotEmpty()) {
                        markdown.append("- **Available Weights**: ")
                        val weightsStr = equipment.availableWeights
                            .sortedByDescending { it.weight }
                            .joinToString(", ") { "${formatNumber(it.weight)} kg" }
                        markdown.append(weightsStr).append("\n")
                    }
                    if (equipment.extraWeights.isNotEmpty()) {
                        markdown.append("- **Extra Weights**: ")
                        val extraStr = equipment.extraWeights
                            .sortedByDescending { it.weight }
                            .joinToString(", ") { "${formatNumber(it.weight)} kg" }
                        markdown.append(extraStr).append("\n")
                    }
                }
                
                is WeightVest -> {
                    if (equipment.availableWeights.isNotEmpty()) {
                        markdown.append("- **Available Weights**: ")
                        val weightsStr = equipment.availableWeights
                            .sortedByDescending { it.weight }
                            .joinToString(", ") { "${formatNumber(it.weight)} kg" }
                        markdown.append(weightsStr).append("\n")
                    }
                }
                
                is PlateLoadedCable -> {
                    if (equipment.availablePlates.isNotEmpty()) {
                        markdown.append("- **Available Plates**: ")
                        val platesStr = equipment.availablePlates
                            .sortedByDescending { it.weight }
                            .joinToString(", ") { "${formatNumber(it.weight)} kg" }
                        markdown.append(platesStr).append("\n")
                    }
                }
                
                else -> {
                    // Generic or other types - no additional details needed
                }
            }
            
            markdown.append("\n")
        }
    }
    
    // Workout Plans Section
    markdown.append("## Workout Plans\n\n")
    
    val sortedPlans = workoutStore.workoutPlans.sortedBy { it.order }
    val workoutsById = workoutStore.workouts.associateBy { it.id }
    
    if (sortedPlans.isEmpty() && workoutStore.workouts.isEmpty()) {
        markdown.append("No workouts configured.\n\n")
    } else {
        // Group workouts by plan
        sortedPlans.forEach { plan ->
            markdown.append("### ${plan.name}\n\n")
            
            val planWorkouts = plan.workoutIds
                .mapNotNull { workoutsById[it] }
                .sortedBy { it.order }
            
            if (planWorkouts.isEmpty()) {
                markdown.append("No workouts in this plan.\n\n")
            } else {
                planWorkouts.forEachIndexed { index, workout ->
                    appendWorkoutDetails(markdown, workout, index + 1, workoutStore)
                }
            }
        }
        
        // Show unassigned workouts
        val unassignedWorkouts = workoutStore.workouts
            .filter { it.workoutPlanId == null }
            .sortedBy { it.order }
        
        if (unassignedWorkouts.isNotEmpty()) {
            markdown.append("### ").append(UNASSIGNED_PLAN_NAME).append("\n\n")
            unassignedWorkouts.forEachIndexed { index, workout ->
                appendWorkoutDetails(markdown, workout, index + 1, workoutStore)
            }
        }
    }
    
    return markdown.toString()
}

private fun appendWorkoutDetails(markdown: StringBuilder, workout: Workout, index: Int, workoutStore: WorkoutStore) {
    markdown.append("### ${index}. ${workout.name}\n\n")
    
    if (workout.description.isNotEmpty()) {
        markdown.append("*${workout.description}*\n\n")
    }
    
    if (workout.workoutComponents.isEmpty()) {
        markdown.append("No components configured.\n\n")
    } else {
        val processedExercises = mutableListOf<Exercise>()

        workout.workoutComponents.forEachIndexed { componentIndex, component ->
            when (component) {
                is Exercise -> {
                    val warmupContext = WarmupContextBuilder.build(
                        exercise = component,
                        priorExercises = processedExercises,
                        isSupersetFollowUp = false
                    )
                    appendExerciseDetails(
                        markdown,
                        component,
                        componentIndex + 1,
                        workoutStore,
                        warmupContext,
                        processedExercises
                    )
                    processedExercises.add(component)
                }
                is Superset -> {
                    val hasRestAfter = componentIndex + 1 < workout.workoutComponents.size && 
                                      workout.workoutComponents[componentIndex + 1] is com.gabstra.myworkoutassistant.shared.workoutcomponents.Rest
                    appendSupersetDetails(markdown, component, componentIndex + 1, workoutStore, hasRestAfter)
                    processedExercises.addAll(component.exercises)
                }
                is Rest -> {
                    markdown.append("${componentIndex + 1}. **Rest**: ${component.timeInSeconds} seconds\n\n")
                }
            }
        }
    }
}

private fun appendExerciseDetails(
    markdown: StringBuilder,
    exercise: Exercise,
    index: Int,
    workoutStore: WorkoutStore,
    warmupContext: WarmupContext?,
    priorExercises: List<Exercise> = emptyList()
) {
    markdown.append("${index}. **${exercise.name}**\n\n")
    
    markdown.append("  - **Type**: ${exercise.exerciseType.name}\n")
    
    val equipment = exercise.equipmentId?.let { equipmentId ->
        workoutStore.equipments.find { it.id == equipmentId }
    }
    if (equipment != null) {
        markdown.append("  - **Equipment**: ${equipment.name}\n")
    }
    
    if (exercise.exerciseType == ExerciseType.BODY_WEIGHT && exercise.bodyWeightPercentage != null) {
        markdown.append("  - **Body Weight Percentage**: ${formatNumber(exercise.bodyWeightPercentage)}%\n")
    }
    
    if (exercise.exerciseType != ExerciseType.COUNTDOWN && exercise.exerciseType != ExerciseType.COUNTUP) {
        markdown.append("  - **Rep Range**: ${exercise.minReps}-${exercise.maxReps}\n")
    }
    
    if (exercise.exerciseType == ExerciseType.WEIGHT) {
        val minLoadPct = exercise.minLoadPercent.roundToInt()
        val maxLoadPct = exercise.maxLoadPercent.roundToInt()
        markdown.append("  - **Load Range**: ${minLoadPct}%-${maxLoadPct}%\n")
    }
    
    if (exercise.lowerBoundMaxHRPercent != null && exercise.upperBoundMaxHRPercent != null) {
        markdown.append("  - **Heart Rate Zone**: ${formatNumber(exercise.lowerBoundMaxHRPercent.toDouble() * 100)}%-${formatNumber(exercise.upperBoundMaxHRPercent.toDouble() * 100)}% of max HR\n")
    }
    
    if (exercise.generateWarmUpSets) {
        markdown.append("  - **Warm-up Sets**: ")
        
        // Generate warmup sets if possible (only for WEIGHT exercises with equipment)
        if (exercise.exerciseType == ExerciseType.WEIGHT && exercise.equipmentId != null) {
            val equipment = workoutStore.equipments.find { it.id == exercise.equipmentId }
            if (equipment != null && exercise.sets.isNotEmpty()) {
                val firstWorkSet = exercise.sets.firstOrNull { it !is RestSet && it is WeightSet }
                if (firstWorkSet is WeightSet) {
                    val workWeight = firstWorkSet.weight
                    val workReps = firstWorkSet.reps
                    val availableTotals = equipment.getWeightsCombinationsNoExtra()
                    
                    val warmups = if (equipment is Barbell) {
                        WarmupPlanner.buildWarmupSetsForBarbell(
                            availableTotals = availableTotals,
                            workWeight = workWeight,
                            workReps = workReps,
                            barbell = equipment,
                            exercise = exercise,
                            priorExercises = priorExercises,
                            initialSetup = emptyList(),
                            maxWarmups = 4
                        )
                    } else {
                        WarmupPlanner.buildWarmupSets(
                            availableTotals = availableTotals,
                            workWeight = workWeight,
                            workReps = workReps,
                            exercise = exercise,
                            priorExercises = priorExercises,
                            equipment = equipment,
                            maxWarmups = 4
                        )
                    }
                    
                    if (warmups.isNotEmpty()) {
                        markdown.append("\n")
                        warmups.forEachIndexed { index, (weight, reps) ->
                            markdown.append("    Warm-up ${index + 1}: ${formatNumber(weight)} kg × $reps reps\n")
                        }
                    } else {
                        markdown.append("Enabled\n")
                    }
                } else {
                    markdown.append("Enabled\n")
                }
            } else {
                markdown.append("Enabled\n")
            }
        } else if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
            markdown.append("Enabled (requires body weight to calculate)\n")
        } else {
            markdown.append("Enabled\n")
        }
    }
    
    if (exercise.notes.isNotEmpty()) {
        markdown.append("  - **Notes**: ${exercise.notes}\n")
    }
    
    if (exercise.sets.isEmpty()) {
        markdown.append("  - **Sets**: None configured\n")
    } else {
        markdown.append("  - **Sets**:\n")
        var workSetNumber = 0
        val hasIntraSetRest = exercise.intraSetRestInSeconds != null && exercise.intraSetRestInSeconds!! > 0
        
        exercise.sets.forEachIndexed { index, set ->
            if (set !is RestSet) {
                workSetNumber++
                val setStr = formatSetInline(set, workSetNumber)
                
                if (hasIntraSetRest) {
                    markdown.append("    Set $workSetNumber (Side A): $setStr\n")
                    markdown.append("\tRest: ${exercise.intraSetRestInSeconds} seconds\n")
                    markdown.append("    Set $workSetNumber (Side B): $setStr\n")
                } else {
                    markdown.append("    Set $workSetNumber: $setStr\n")
                }
                
                // Look ahead to see if there's a rest set immediately after this work set
                if (index + 1 < exercise.sets.size && exercise.sets[index + 1] is RestSet) {
                    val restSet = exercise.sets[index + 1] as RestSet
                    markdown.append("\tRest: ${restSet.timeInSeconds} seconds\n")
                }
            }
        }
    }
    
    markdown.append("\n")
}

private fun appendSupersetDetails(markdown: StringBuilder, superset: Superset, index: Int, workoutStore: WorkoutStore, hasRestAfter: Boolean = false) {
    markdown.append("${index}. **Superset**\n\n")
    
    // Show exercise details first
    superset.exercises.forEachIndexed { exerciseIndex, exercise ->
        markdown.append("  Exercise ${exerciseIndex + 1}: **${exercise.name}**\n")
        
        markdown.append("    - Type: ${exercise.exerciseType.name}")
        
        val equipment = exercise.equipmentId?.let { equipmentId ->
            workoutStore.equipments.find { it.id == equipmentId }
        }
        if (equipment != null) {
            markdown.append(" | Equipment: ${equipment.name}")
        }
        markdown.append("\n")
    }
    
    markdown.append("\n")
    markdown.append("  **Execution Order**:\n\n")
    
    // Build lists of work sets (excluding rest sets) for each exercise
    val exerciseWorkSets = superset.exercises.map { exercise ->
        exercise.sets.filter { it !is RestSet }
    }
    
    // Determine number of rounds (minimum number of sets across exercises)
    val rounds = exerciseWorkSets.minOfOrNull { it.size } ?: 0
    
    // Display alternating sets with rest after each exercise (matching WorkoutViewModel logic)
    for (round in 0 until rounds) {
        val isLastRound = round == rounds - 1
        superset.exercises.forEachIndexed { exerciseIndex, exercise ->
            if (round < exerciseWorkSets[exerciseIndex].size) {
                val set = exerciseWorkSets[exerciseIndex][round]
                val setStr = formatSetInline(set, round + 1)
                val hasIntraSetRest = exercise.intraSetRestInSeconds != null && exercise.intraSetRestInSeconds!! > 0
                
                if (hasIntraSetRest) {
                    markdown.append("    ${exercise.name} (Side A): $setStr\n")
                    markdown.append("\tRest: ${exercise.intraSetRestInSeconds} seconds\n")
                    markdown.append("    ${exercise.name} (Side B): $setStr\n")
                } else {
                    markdown.append("    ${exercise.name}: $setStr\n")
                }
                
                // Add rest after each exercise (from restSecondsByExercise, matching WorkoutViewModel)
                // Skip last exercise's rest in last round if there's a workout Rest after this superset
                val isLastExerciseInLastRound = isLastRound && exerciseIndex == superset.exercises.size - 1
                val shouldSkipRest = isLastExerciseInLastRound && hasRestAfter
                
                if (!shouldSkipRest) {
                    val restAfter = superset.restSecondsByExercise[exercise.id] ?: 0
                    if (restAfter > 0) {
                        markdown.append("\tRest: $restAfter seconds\n")
                    }
                }
            }
        }
        markdown.append("\n")
    }
}

private fun formatSet(set: Set, setNumber: Int): String {
    val prefix = "Set $setNumber: "
    val setStr = formatSetInline(set, setNumber)
    return prefix + setStr
}

private fun formatSetInline(set: Set, setNumber: Int): String {
    return when (set) {
        is WeightSet -> {
            var str = "${formatNumber(set.weight)} kg × ${set.reps} reps"
            if (set.subCategory != SetSubCategory.WorkSet) {
                str += " [${set.subCategory.name}]"
            }
            str
        }
        is BodyWeightSet -> {
            var str = "Body weight"
            if (set.additionalWeight > 0) {
                str += " + ${formatNumber(set.additionalWeight)} kg"
            } else if (set.additionalWeight < 0) {
                str += " - ${formatNumber(-set.additionalWeight)} kg"
            }
            str += " × ${set.reps} reps"
            if (set.subCategory != SetSubCategory.WorkSet) {
                str += " [${set.subCategory.name}]"
            }
            str
        }
        is TimedDurationSet -> {
            val minutes = set.timeInMillis / 60000
            val seconds = (set.timeInMillis % 60000) / 1000
            "${minutes}:${String.format("%02d", seconds)}"
        }
        is EnduranceSet -> {
            val minutes = set.timeInMillis / 60000
            val seconds = (set.timeInMillis % 60000) / 1000
            "${minutes}:${String.format("%02d", seconds)} (endurance)"
        }
        is RestSet -> {
            "${set.timeInSeconds} seconds rest"
        }
    }
}

private fun EquipmentType.toDisplayText(): String {
    return when (this) {
        EquipmentType.GENERIC -> "Generic"
        EquipmentType.BARBELL -> "Barbell"
        EquipmentType.DUMBBELLS -> "Dumbbells"
        EquipmentType.DUMBBELL -> "Dumbbell"
        EquipmentType.PLATELOADEDCABLE -> "Plate Loaded Cable"
        EquipmentType.WEIGHTVEST -> "Weight Vest"
        EquipmentType.MACHINE -> "Machine"
        EquipmentType.IRONNECK -> "Iron Neck"
        EquipmentType.ACCESSORY -> "Accessory"
    }
}
