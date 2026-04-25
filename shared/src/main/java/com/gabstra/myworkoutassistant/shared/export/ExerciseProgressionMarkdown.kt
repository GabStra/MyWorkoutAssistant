package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.ExerciseSessionProgression
import com.gabstra.myworkoutassistant.shared.SetHistory
import com.gabstra.myworkoutassistant.shared.formatNumber
import com.gabstra.myworkoutassistant.shared.setdata.BodyWeightSetData
import com.gabstra.myworkoutassistant.shared.setdata.WeightSetData
import com.gabstra.myworkoutassistant.shared.utils.SimpleSet

internal fun appendExerciseProgressionMarkdown(
    markdown: StringBuilder,
    progression: ExerciseSessionProgression,
    activeSetHistories: List<SetHistory>,
    achievableWeights: List<Double>?,
    previousActiveSetHistories: List<SetHistory>? = null,
) {
    markdown.append("#### Progression Context\n")

    val executedSets = activeSetHistories.mapNotNull { setHistory ->
        when (val setData = setHistory.setData) {
            is WeightSetData -> {
                val adjustedWeight = normalizeWeightForExport(setData.actualWeight, achievableWeights)
                SimpleSet(adjustedWeight, setData.actualReps)
            }
            is BodyWeightSetData -> SimpleSet(setData.getWeight(), setData.actualReps)
            else -> null
        }
    }

    previousActiveSetHistories?.let { previousHistories ->
        val previousSets = previousHistories.mapNotNull { setHistory ->
            when (val setData = setHistory.setData) {
                is WeightSetData -> {
                    val adjustedWeight = normalizeWeightForExport(setData.actualWeight, achievableWeights)
                    SimpleSet(adjustedWeight, setData.actualReps)
                }
                is BodyWeightSetData -> SimpleSet(setData.getWeight(), setData.actualReps)
                else -> null
            }
        }
        if (previousSets.isEmpty()) {
            markdown.append("- Previous: none\n")
        } else {
            markdown.append("- Previous: ${previousSets.joinToString(", ") { "${formatNumber(it.weight)} kg x ${it.reps}" }}\n")
        }
    }

    if (progression.expectedSets.isNotEmpty()) {
        val expectedSetsStr = progression.expectedSets.joinToString(", ") {
            "${formatNumber(it.weight)} kg x ${it.reps}"
        }
        markdown.append("- Expected: $expectedSetsStr\n")
    }

    val expectedSetCount = progression.expectedSets.size
    val executedSetCount = executedSets.size
    if (expectedSetCount != executedSetCount) {
        markdown.append("- Note: Expected $expectedSetCount sets but executed $executedSetCount sets.\n")
    }

    markdown.append("\n")
}
