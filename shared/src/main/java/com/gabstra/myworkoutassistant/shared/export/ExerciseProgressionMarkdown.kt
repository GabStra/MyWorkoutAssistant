package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.formatNumber
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.utils.Ternary
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet
import kotlin.math.abs

internal fun appendExerciseProgressionMarkdown(
    markdown: StringBuilder,
    progression: ExerciseSessionProgression,
    activeSetHistories: List<SetHistory>,
    achievableWeights: List<Double>?,
) {
    markdown.append("### Progression\n")
    markdown.append("- State: ${progression.progressionState.name}\n")

    val executedSets = activeSetHistories.mapNotNull { setHistory ->
        when (val setData = setHistory.setData) {
            is WeightSetData -> {
                val (adjustedWeight, _) = adjustWeightAndVolumeProgression(
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

private fun adjustWeightAndVolumeProgression(
    actualWeight: Double,
    reps: Int,
    achievableWeights: List<Double>?
): Pair<Double, Double> {
    if (actualWeight <= 0.0 || reps <= 0) {
        return actualWeight to (actualWeight * reps)
    }
    val adjustedWeight = findClosestAchievableWeightProgression(actualWeight, achievableWeights)
    return adjustedWeight to adjustedWeight * reps
}

private fun findClosestAchievableWeightProgression(
    targetWeight: Double,
    achievableWeights: List<Double>?
): Double {
    if (achievableWeights.isNullOrEmpty()) return targetWeight
    return achievableWeights.minByOrNull { achievable -> abs(achievable - targetWeight) } ?: targetWeight
}
