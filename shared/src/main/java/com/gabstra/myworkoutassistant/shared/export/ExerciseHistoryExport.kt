package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgressionDao
import com.gabstra.myworkoutassistant.shared.ExerciseType
import com.gabstra.myworkoutassistant.shared.SetHistoryDao
import com.gabstra.myworkoutassistant.shared.Workout
import com.gabstra.myworkoutassistant.shared.WorkoutHistoryDao
import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.formatNumber
import com.gabstra.myworkoutassistant.shared.getHeartRateFromPercentage
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.EnduranceSetData
import com.gabstra.myworkoutassistant.shared.setdata.RestSetData
import com.gabstra.myworkoutassistant.shared.setdata.SetSubCategory
import com.gabstra.myworkoutassistant.shared.setdata.TimedDurationSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Exercise
import com.gabstra.myworkoutassistant.shared.workoutcomponents.Superset
import com.gabstra.myworkoutassistant.shared.equipments.WeightLoadedEquipment
import java.time.Duration
import java.util.Calendar
import kotlin.math.abs

sealed class ExerciseHistoryMarkdownResult {
    data class Success(val markdown: String) : ExerciseHistoryMarkdownResult()
    data class Failure(val message: String) : ExerciseHistoryMarkdownResult()
}

suspend fun buildExerciseHistoryMarkdown(
    exercise: Exercise,
    workoutHistoryDao: WorkoutHistoryDao,
    setHistoryDao: SetHistoryDao,
    exerciseSessionProgressionDao: ExerciseSessionProgressionDao,
    workouts: List<Workout>,
    workoutStore: WorkoutStore
): ExerciseHistoryMarkdownResult {
    val workoutsContainingExercise = workouts.filter { workout ->
        workout.workoutComponents.any { component ->
            when (component) {
                is Exercise -> component.id == exercise.id
                is Superset -> component.exercises.any { it.id == exercise.id }
                else -> false
            }
        }
    }

    if (workoutsContainingExercise.isEmpty()) {
        return ExerciseHistoryMarkdownResult.Failure("No workouts found containing this exercise")
    }

    val allWorkoutHistories = workoutsContainingExercise
        .flatMap { workout -> workoutHistoryDao.getWorkoutsByWorkoutId(workout.id) }
        .filter { it.isDone }
        .sortedBy { it.date }

    if (allWorkoutHistories.isEmpty()) {
        return ExerciseHistoryMarkdownResult.Failure("No completed sessions found for this exercise")
    }

    val userAge = Calendar.getInstance().get(Calendar.YEAR) - workoutStore.birthDateYear
    val markdown = StringBuilder()

    val equipment = exercise.equipmentId?.let { equipmentId ->
        workoutStore.equipments.find { it.id == equipmentId }
    }
    val achievableWeights = equipment?.getWeightsCombinations()?.sorted()

    markdown.append("# ${exercise.name}\n")
    markdown.append("Type: ${exercise.exerciseType}")

    if (exercise.equipmentId != null) {
        if (equipment != null) {
            markdown.append(" | Equipment: ${equipment.name}")
            if (exercise.exerciseType == ExerciseType.WEIGHT && !achievableWeights.isNullOrEmpty()) {
                markdown.append(
                    " | Weights: ${achievableWeights.joinToString(",") { weight -> formatNumber(weight) }} kg"
                )
            }
        } else {
            markdown.append(" | Equipment: Unknown")
        }
    }

    if (exercise.exerciseType == ExerciseType.BODY_WEIGHT) {
        markdown.append(" | BW: ${formatNumber(workoutStore.weightKg)} kg")
    }

    if (exercise.notes.isNotEmpty()) {
        markdown.append(" | Notes: ${exercise.notes}")
    }
    markdown.append("\n\n")

    val firstSession = allWorkoutHistories.first()
    val lastSession = allWorkoutHistories.last()
    markdown.append(
        "Sessions: ${allWorkoutHistories.size} | Range: ${firstSession.date} to ${lastSession.date}\n\n"
    )

    for ((sessionIndex, workoutHistory) in allWorkoutHistories.withIndex()) {
        val workout = workoutsContainingExercise.find { it.id == workoutHistory.workoutId }
        val workoutName = workout?.name ?: "Unknown Workout"
        val setHistories = setHistoryDao.getSetHistoriesByWorkoutHistoryIdAndExerciseId(
            workoutHistory.id,
            exercise.id
        ).sortedBy { it.order }

        val activeSetHistories = setHistories.filter { it.setData !is RestSetData }
        
        // Skip session if there are no active sets (only rest sets)
        if (activeSetHistories.isEmpty()) {
            continue
        }

        val progressionData = exerciseSessionProgressionDao.getByWorkoutHistoryIdAndExerciseId(
            workoutHistory.id,
            exercise.id
        )

        markdown.append(
            "## S${sessionIndex + 1}: ${workoutHistory.date} ${workoutHistory.time} | $workoutName | Dur: ${formatDuration(workoutHistory.duration)}"
        )

        if (workoutHistory.heartBeatRecords.isNotEmpty() && workoutHistory.heartBeatRecords.any { it > 0 }) {
            val validHRRecords = workoutHistory.heartBeatRecords.filter { it > 0 }
            val avgHR = validHRRecords.average().toInt()
            val minHR = validHRRecords.minOrNull() ?: 0
            val maxHR = validHRRecords.maxOrNull() ?: 0
            markdown.append(" | HR: Avg ${avgHR} Min:${minHR} Max:${maxHR}")
        }
        markdown.append("\n")

        progressionData?.let { progression ->
            markdown.append("### Progression\n")
            markdown.append("- State: ${progression.progressionState.name}\n")

            // Extract executed sets from activeSetHistories
            val executedSets = activeSetHistories.mapNotNull { setHistory ->
                when (val setData = setHistory.setData) {
                    is WeightSetData -> {
                        val (adjustedWeight, _) = adjustWeightAndVolume(
                            setData.actualWeight,
                            setData.actualReps,
                            achievableWeights
                        )
                        SimpleSet(adjustedWeight, setData.actualReps)
                    }
                    is BodyWeightSetData -> SimpleSet(setData.getWeight(), setData.actualReps)
                    else -> null
                }
            }

            if (progression.expectedSets.isNotEmpty()) {
                val expectedSetsStr = progression.expectedSets.joinToString(", ") {
                    "${formatNumber(it.weight)}kg×${it.reps}"
                }
                markdown.append("- Expected: $expectedSetsStr\n")
            }

            if (executedSets.isNotEmpty()) {
                val executedSetsStr = executedSets.joinToString(", ") {
                    "${formatNumber(it.weight)}kg×${it.reps}"
                }
                markdown.append("- Executed: $executedSetsStr\n")
            }

            // Add set-by-set differences when it makes sense
            val shouldShowSetDifferences = progression.expectedSets.isNotEmpty() &&
                    executedSets.isNotEmpty() &&
                    progression.expectedSets.size == executedSets.size

            if (shouldShowSetDifferences) {
                val setDifferences = progression.expectedSets.zip(executedSets).mapIndexed { index, (expected, executed) ->
                    val weightDiff = executed.weight - expected.weight
                    val repsDiff = executed.reps - expected.reps
                    val expectedVolume = expected.weight * expected.reps
                    val executedVolume = executed.weight * executed.reps
                    val volumeDiff = executedVolume - expectedVolume

                    val weightDiffStr = if (weightDiff >= 0) "+${formatNumber(weightDiff)}" else formatNumber(weightDiff)
                    val repsDiffStr = if (repsDiff >= 0) "+$repsDiff" else repsDiff.toString()
                    val volumeDiffStr = if (volumeDiff >= 0) "+${formatNumber(volumeDiff)}" else formatNumber(volumeDiff)

                    "S${index + 1}: Exp ${formatNumber(expected.weight)}kg×${expected.reps} Exec ${formatNumber(executed.weight)}kg×${executed.reps} Δw:${weightDiffStr}kg Δr:${repsDiffStr} Δv:${volumeDiffStr}kg"
                }
                val allSetsEqual = progression.expectedSets.zip(executedSets).all { (expected, executed) -> expected == executed }
                if (!allSetsEqual) {
                    markdown.append("- Set Differences: ${setDifferences.joinToString(" | ")}\n")
                }
            }

            val expectedSetCount = progression.expectedSets.size
            val executedSetCount = executedSets.size
            if (expectedSetCount != executedSetCount) {
                markdown.append("- Note: Expected $expectedSetCount sets but executed $executedSetCount sets.\n")
            }

            val vsExpectedIcon = when (progression.vsExpected) {
                Ternary.ABOVE -> "↑"
                Ternary.EQUAL -> "="
                Ternary.BELOW -> "↓"
                Ternary.MIXED -> "~"
            }
            val vsPreviousIcon = when (progression.vsPrevious) {
                Ternary.ABOVE -> "↑"
                Ternary.EQUAL -> "="
                Ternary.BELOW -> "↓"
                Ternary.MIXED -> "~"
            }
            markdown.append("- Comparison: vs Exp ${progression.vsExpected.name} $vsExpectedIcon | vs Prev ${progression.vsPrevious.name} $vsPreviousIcon\n")
            markdown.append("- Vol: Prev ${formatNumber(progression.previousSessionVolume)}kg | Exp ${formatNumber(progression.expectedVolume)}kg | Exec ${formatNumber(progression.executedVolume)}kg\n")

            markdown.append("\n")
        }

        var totalVolume = 0.0
        var totalDuration = 0

        for ((setIndex, setHistory) in activeSetHistories.withIndex()) {
            val setLine = StringBuilder("S${setIndex + 1}: ")
            when (val setData = setHistory.setData) {
                is WeightSetData -> {
                    val (adjustedWeight, adjustedVolume) = adjustWeightAndVolume(
                        setData.actualWeight,
                        setData.actualReps,
                        achievableWeights
                    )
                    setLine.append("${formatNumber(adjustedWeight)}kg×${setData.actualReps} Vol:${formatNumber(adjustedVolume)}kg")
                    if (setData.subCategory == SetSubCategory.RestPauseSet) setLine.append(" [RP]")
                    totalVolume += adjustedVolume
                }
                is BodyWeightSetData -> {
                    val totalWeight = setData.getWeight()
                    setLine.append("${formatNumber(totalWeight)}kg×${setData.actualReps} Vol:${formatNumber(setData.volume)}kg")
                    if (setData.subCategory == SetSubCategory.RestPauseSet) setLine.append(" [RP]")
                    totalVolume += setData.volume
                }
                is TimedDurationSetData -> {
                    val durationSeconds = (setData.endTimer - setData.startTimer) / 1000
                    setLine.append("Dur:${formatDuration(durationSeconds)}")
                    totalDuration += durationSeconds
                }
                is EnduranceSetData -> {
                    val durationSeconds = setData.endTimer / 1000
                    setLine.append("Dur:${formatDuration(durationSeconds)}")
                    totalDuration += durationSeconds
                }
                else -> setLine.append("Rest/Other")
            }

            if (workoutHistory.heartBeatRecords.isNotEmpty() &&
                setHistory.startTime != null &&
                setHistory.endTime != null
            ) {
                val hrTimeOffset = Duration.between(
                    workoutHistory.startTime,
                    setHistory.startTime
                ).seconds.toInt()

                val setDuration = Duration.between(
                    setHistory.startTime,
                    setHistory.endTime
                ).seconds.toInt()

                val startSampleIndex = hrTimeOffset * 2
                val endSampleIndex = (hrTimeOffset + setDuration) * 2

                if (startSampleIndex >= 0 && endSampleIndex <= workoutHistory.heartBeatRecords.size) {
                    val setHRRecords = workoutHistory.heartBeatRecords
                        .subList(startSampleIndex, minOf(endSampleIndex, workoutHistory.heartBeatRecords.size))
                        .filter { it > 0 }

                    if (setHRRecords.isNotEmpty()) {
                        val setAvgHR = setHRRecords.average().toInt()
                        val setMinHR = setHRRecords.minOrNull() ?: 0
                        val setMaxHR = setHRRecords.maxOrNull() ?: 0
                        setLine.append(" HR:${setAvgHR}(${setMinHR}-${setMaxHR})")

                        if (exercise.lowerBoundMaxHRPercent != null && exercise.upperBoundMaxHRPercent != null) {
                            val lowHr = getHeartRateFromPercentage(
                                exercise.lowerBoundMaxHRPercent!!,
                                userAge,
                                workoutStore.measuredMaxHeartRate,
                                workoutStore.restingHeartRate
                            )
                            val highHr = getHeartRateFromPercentage(
                                exercise.upperBoundMaxHRPercent!!,
                                userAge,
                                workoutStore.measuredMaxHeartRate,
                                workoutStore.restingHeartRate
                            )

                            val hrInZoneCount = setHRRecords.count { it in lowHr..highHr }
                            val zonePercentage = if (setHRRecords.isNotEmpty()) {
                                (hrInZoneCount.toFloat() / setHRRecords.size * 100).toInt()
                            } else 0

                            setLine.append(" Zone:${zonePercentage}%")
                        }
                    }
                }
            }

            markdown.append(setLine.toString()).append("\n")
        }

        val totalsLine = StringBuilder()
        if (totalVolume > 0) {
            totalsLine.append("Total Vol: ${formatNumber(totalVolume)}kg")
        }
        if (totalDuration > 0) {
            if (totalsLine.isNotEmpty()) totalsLine.append(" | ")
            totalsLine.append("Total Dur: ${formatDuration(totalDuration)}")
        }

        if (exercise.lowerBoundMaxHRPercent != null &&
            exercise.upperBoundMaxHRPercent != null &&
            workoutHistory.heartBeatRecords.isNotEmpty()
        ) {
            val lowHr = getHeartRateFromPercentage(
                exercise.lowerBoundMaxHRPercent!!,
                userAge,
                workoutStore.measuredMaxHeartRate,
                workoutStore.restingHeartRate
            )
            val highHr = getHeartRateFromPercentage(
                exercise.upperBoundMaxHRPercent!!,
                userAge,
                workoutStore.measuredMaxHeartRate,
                workoutStore.restingHeartRate
            )
            val validHRRecords = workoutHistory.heartBeatRecords.filter { it > 0 }
            val hrInZoneCount = validHRRecords.count { it in lowHr..highHr }
            val zonePercentage = if (validHRRecords.isNotEmpty()) {
                (hrInZoneCount.toFloat() / validHRRecords.size * 100).toInt()
            } else 0

            if (totalsLine.isNotEmpty()) totalsLine.append(" | ")
            totalsLine.append("HR Zone(${lowHr}-${highHr}): ${zonePercentage}%")
        }

        if (totalsLine.isNotEmpty()) {
            markdown.append(totalsLine.toString()).append("\n")
        }
        markdown.append("\n")
    }

    return ExerciseHistoryMarkdownResult.Success(markdown.toString())
}

private fun formatDuration(seconds: Int): String {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60

    return if (hours > 0) {
        String.format("%02d:%02d:%02d", hours, minutes, remainingSeconds)
    } else {
        String.format("%02d:%02d", minutes, remainingSeconds)
    }
}

private fun adjustWeightAndVolume(
    actualWeight: Double,
    reps: Int,
    achievableWeights: List<Double>?
): Pair<Double, Double> {
    if (actualWeight <= 0.0 || reps <= 0) {
        return actualWeight to (actualWeight * reps)
    }

    val adjustedWeight = findClosestAchievableWeight(actualWeight, achievableWeights)
    return adjustedWeight to adjustedWeight * reps
}

private fun findClosestAchievableWeight(
    targetWeight: Double,
    achievableWeights: List<Double>?
): Double {
    if (achievableWeights.isNullOrEmpty()) return targetWeight
    return achievableWeights.minByOrNull { achievable -> abs(achievable - targetWeight) } ?: targetWeight
}
