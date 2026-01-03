package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.ExerciseType
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
                    markdown.append("- **Bar Length**: ${equipment.barLength} mm\n")
                    if (equipment.availablePlates.isNotEmpty()) {
                        markdown.append("- **Available Plates**: ")
                        val platesStr = equipment.availablePlates
                            .sortedByDescending { it.weight }
                            .joinToString(", ") { plate ->
                                "${formatNumber(plate.weight)} kg (${formatNumber(plate.thickness)} mm)"
                            }
                        markdown.append(platesStr).append("\n")
                    }
                    val achievableWeights = equipment.getWeightsCombinations().sorted().take(20)
                    if (achievableWeights.isNotEmpty()) {
                        markdown.append("- **Example Weight Combinations**: ")
                        markdown.append(achievableWeights.joinToString(", ") { "${formatNumber(it)} kg" })
                        if (equipment.getWeightsCombinations().size > 20) {
                            markdown.append(" (and ${equipment.getWeightsCombinations().size - 20} more)")
                        }
                        markdown.append("\n")
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
                        markdown.append("- **Max Extra Weights Per Loading Point**: ${equipment.maxExtraWeightsPerLoadingPoint}\n")
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
                        markdown.append("- **Max Extra Weights Per Loading Point**: ${equipment.maxExtraWeightsPerLoadingPoint}\n")
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
                        markdown.append("- **Max Extra Weights Per Loading Point**: ${equipment.maxExtraWeightsPerLoadingPoint}\n")
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
                    markdown.append("- **Bar Length**: ${equipment.barLength} mm\n")
                    if (equipment.availablePlates.isNotEmpty()) {
                        markdown.append("- **Available Plates**: ")
                        val platesStr = equipment.availablePlates
                            .sortedByDescending { it.weight }
                            .joinToString(", ") { plate ->
                                "${formatNumber(plate.weight)} kg (${formatNumber(plate.thickness)} mm)"
                            }
                        markdown.append(platesStr).append("\n")
                    }
                }
                
                else -> {
                    // Generic or other types
                    val achievableWeights = equipment.getWeightsCombinations().sorted().take(20)
                    if (achievableWeights.isNotEmpty()) {
                        markdown.append("- **Example Weight Combinations**: ")
                        markdown.append(achievableWeights.joinToString(", ") { "${formatNumber(it)} kg" })
                        if (equipment.getWeightsCombinations().size > 20) {
                            markdown.append(" (and ${equipment.getWeightsCombinations().size - 20} more)")
                        }
                        markdown.append("\n")
                    }
                }
            }
            
            markdown.append("\n")
        }
    }
    
    // Workout Plans Section
    markdown.append("## Workout Plans\n\n")
    
    val activeWorkouts = workoutStore.workouts.filter { it.enabled && it.isActive }.sortedBy { it.order }
    val inactiveWorkouts = workoutStore.workouts.filterNot { it.enabled && it.isActive }
    
    if (activeWorkouts.isEmpty() && inactiveWorkouts.isEmpty()) {
        markdown.append("No workouts configured.\n\n")
    } else {
        if (activeWorkouts.isNotEmpty()) {
            markdown.append("### Active Workouts\n\n")
            activeWorkouts.forEachIndexed { index, workout ->
                appendWorkoutDetails(markdown, workout, index + 1, workoutStore)
            }
        }
        
        if (inactiveWorkouts.isNotEmpty()) {
            markdown.append("### Inactive Workouts\n\n")
            inactiveWorkouts.forEachIndexed { index, workout ->
                appendWorkoutDetails(markdown, workout, index + 1, workoutStore)
            }
        }
    }
    
    return markdown.toString()
}

private fun appendWorkoutDetails(markdown: StringBuilder, workout: Workout, index: Int, workoutStore: WorkoutStore) {
    markdown.append("#### ${index}. ${workout.name}\n\n")
    
    if (workout.description.isNotEmpty()) {
        markdown.append("*${workout.description}*\n\n")
    }
    
    markdown.append("**Metadata**:\n")
    markdown.append("- Order: ${workout.order}\n")
    markdown.append("- Enabled: ${workout.enabled}\n")
    markdown.append("- Active: ${workout.isActive}\n")
    markdown.append("- Use Polar Device: ${workout.usePolarDevice}\n")
    markdown.append("- Creation Date: ${workout.creationDate}\n")
    if (workout.timesCompletedInAWeek != null) {
        markdown.append("- Times Completed Per Week: ${workout.timesCompletedInAWeek}\n")
    }
    markdown.append("\n")
    
    if (workout.workoutComponents.isEmpty()) {
        markdown.append("No components configured.\n\n")
    } else {
        markdown.append("**Components**:\n\n")
        workout.workoutComponents.forEachIndexed { componentIndex, component ->
            when (component) {
                is Exercise -> {
                    appendExerciseDetails(markdown, component, componentIndex + 1, workoutStore)
                }
                is Superset -> {
                    appendSupersetDetails(markdown, component, componentIndex + 1, workoutStore)
                }
                is Rest -> {
                    markdown.append("${componentIndex + 1}. **Rest** (${component.timeInSeconds} seconds)")
                    if (!component.enabled) markdown.append(" [Disabled]")
                    markdown.append("\n\n")
                }
            }
        }
    }
}

private fun appendExerciseDetails(markdown: StringBuilder, exercise: Exercise, index: Int, workoutStore: WorkoutStore) {
    markdown.append("${index}. **Exercise: ${exercise.name}**")
    if (!exercise.enabled) markdown.append(" [Disabled]")
    markdown.append("\n\n")
    
    markdown.append("  - **Type**: ${exercise.exerciseType.name}\n")
    
    val equipment = exercise.equipmentId?.let { equipmentId ->
        workoutStore.equipments.find { it.id == equipmentId }
    }
    if (equipment != null) {
        markdown.append("  - **Equipment**: ${equipment.name} (${equipment.type.toDisplayText()})\n")
    } else if (exercise.equipmentId != null) {
        markdown.append("  - **Equipment**: Unknown (ID: ${exercise.equipmentId})\n")
    }
    
    if (exercise.muscleGroups != null && exercise.muscleGroups.isNotEmpty()) {
        markdown.append("  - **Primary Muscle Groups**: ")
        markdown.append(exercise.muscleGroups.joinToString(", ") { it.name.replace("_", " ") })
        markdown.append("\n")
    }
    
    if (exercise.secondaryMuscleGroups != null && exercise.secondaryMuscleGroups.isNotEmpty()) {
        markdown.append("  - **Secondary Muscle Groups**: ")
        markdown.append(exercise.secondaryMuscleGroups.joinToString(", ") { it.name.replace("_", " ") })
        markdown.append("\n")
    }
    
    if (exercise.exerciseType == ExerciseType.BODY_WEIGHT && exercise.bodyWeightPercentage != null) {
        markdown.append("  - **Body Weight Percentage**: ${formatNumber(exercise.bodyWeightPercentage)}%\n")
    }
    
    markdown.append("  - **Rep Range**: ${exercise.minReps}-${exercise.maxReps}\n")
    
    if (exercise.exerciseType == ExerciseType.WEIGHT) {
        markdown.append("  - **Load Range**: ${formatNumber(exercise.minLoadPercent * 100)}%-${formatNumber(exercise.maxLoadPercent * 100)}%\n")
    }
    
    if (exercise.lowerBoundMaxHRPercent != null && exercise.upperBoundMaxHRPercent != null) {
        markdown.append("  - **Heart Rate Zone**: ${formatNumber(exercise.lowerBoundMaxHRPercent.toDouble() * 100)}%-${formatNumber(exercise.upperBoundMaxHRPercent.toDouble() * 100)}% of max HR\n")
    }
    
    if (exercise.enableProgression) {
        markdown.append("  - **Progression**: Enabled\n")
        if (exercise.loadJumpDefaultPct != null) {
            markdown.append("    - Default Load Jump: ${formatNumber(exercise.loadJumpDefaultPct * 100)}%\n")
        }
        if (exercise.loadJumpMaxPct != null) {
            markdown.append("    - Max Load Jump: ${formatNumber(exercise.loadJumpMaxPct * 100)}%\n")
        }
        if (exercise.loadJumpOvercapUntil != null) {
            markdown.append("    - Overcap Until: ${exercise.loadJumpOvercapUntil} sessions\n")
        }
    }
    
    if (exercise.generateWarmUpSets) {
        markdown.append("  - **Warm-up Sets**: Enabled\n")
    }
    
    if (exercise.keepScreenOn) {
        markdown.append("  - **Keep Screen On**: Enabled\n")
    }
    
    if (exercise.showCountDownTimer) {
        markdown.append("  - **Countdown Timer**: Enabled\n")
    }
    
    if (exercise.intraSetRestInSeconds != null) {
        markdown.append("  - **Intra-set Rest**: ${exercise.intraSetRestInSeconds} seconds\n")
    }
    
    if (exercise.doNotStoreHistory) {
        markdown.append("  - **History**: Not stored\n")
    }
    
    if (exercise.notes.isNotEmpty()) {
        markdown.append("  - **Notes**: ${exercise.notes}\n")
    }
    
    if (exercise.sets.isEmpty()) {
        markdown.append("  - **Sets**: None configured\n")
    } else {
        markdown.append("  - **Sets**:\n")
        exercise.sets.forEachIndexed { setIndex, set ->
            val setStr = formatSet(set, setIndex + 1)
            markdown.append("    ${setStr}\n")
        }
    }
    
    markdown.append("\n")
}

private fun appendSupersetDetails(markdown: StringBuilder, superset: Superset, index: Int, workoutStore: WorkoutStore) {
    markdown.append("${index}. **Superset**")
    if (!superset.enabled) markdown.append(" [Disabled]")
    markdown.append("\n\n")
    
    markdown.append("  **Exercises**:\n\n")
    superset.exercises.forEachIndexed { exerciseIndex, exercise ->
        markdown.append("  ${exerciseIndex + 1}. ${exercise.name}")
        if (!exercise.enabled) markdown.append(" [Disabled]")
        markdown.append("\n")
        
        val restAfter = superset.restSecondsByExercise[exercise.id]
        if (restAfter != null && restAfter > 0) {
            markdown.append("     - Rest after: ${restAfter} seconds\n")
        }
        
        if (exercise.sets.isNotEmpty()) {
            markdown.append("     - Sets: ")
            val setsStr = exercise.sets.mapIndexed { setIndex, set ->
                formatSetInline(set, setIndex + 1)
            }.joinToString(", ")
            markdown.append(setsStr).append("\n")
        }
    }
    
    markdown.append("\n")
}

private fun formatSet(set: Set, setNumber: Int): String {
    val prefix = "Set $setNumber: "
    return prefix + formatSetInline(set, setNumber)
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
            var str = "${minutes}:${String.format("%02d", seconds)}"
            if (set.autoStart) str += " (auto-start)"
            if (set.autoStop) str += " (auto-stop)"
            str
        }
        is EnduranceSet -> {
            val minutes = set.timeInMillis / 60000
            val seconds = (set.timeInMillis % 60000) / 1000
            var str = "${minutes}:${String.format("%02d", seconds)} (endurance)"
            if (set.autoStart) str += " (auto-start)"
            if (set.autoStop) str += " (auto-stop)"
            str
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
    }
}

