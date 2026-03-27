package com.gabstra.myworkoutassistant.shared.export

import com.gabstra.myworkoutassistant.shared.WorkoutStore
import com.gabstra.myworkoutassistant.shared.formatNumber

internal fun appendLlmExportContextMarkdown(
    markdown: StringBuilder,
    workoutStore: WorkoutStore,
    userAge: Int,
) {
    markdown.append("#### Athlete Context\n\n")
    markdown.append("- Age: $userAge years\n")
    markdown.append("- Weight (kg): ${formatNumber(workoutStore.weightKg)}\n")
    if (workoutStore.measuredMaxHeartRate != null) {
        markdown.append("- Max HR (bpm): ${workoutStore.measuredMaxHeartRate} (measured)\n")
    } else {
        markdown.append("- Max HR: age-based estimate\n")
    }
    if (workoutStore.restingHeartRate != null) {
        markdown.append("- Resting HR (bpm): ${workoutStore.restingHeartRate}\n")
    }
    markdown.append("\n")
}
