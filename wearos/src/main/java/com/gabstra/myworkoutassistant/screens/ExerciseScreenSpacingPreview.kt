package com.gabstra.myworkoutassistant.screens

import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.tooling.preview.PreviewParameter
import androidx.compose.ui.tooling.preview.PreviewParameterProvider
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.shared.workout.state.ProgressionState

internal data class ExerciseScreenSpacingPreviewCase(
    val label: String,
    val scenario: ExercisePreviewScenario,
) {
    override fun toString(): String = label
}

internal class ExerciseScreenMainPageMetadataPreviewProvider : PreviewParameterProvider<ExerciseScreenSpacingPreviewCase> {
    override val values: Sequence<ExerciseScreenSpacingPreviewCase> = sequenceOf(
        ExerciseScreenSpacingPreviewCase(
            label = "Main metadata",
            scenario = ExercisePreviewScenario(
                name = "main_metadata",
                setType = ExercisePreviewSetType.WEIGHT,
                isCalibrationSet = true,
                isAutoRegulationWorkSet = true,
                isUnilateral = true,
                progressionState = ProgressionState.RETRY,
                includeBarbellPage = true,
                includeSupersetMetadata = true,
                includePlateauWarning = true,
                previewSetCount = 3,
                openPage = ExercisePreviewPage.DETAIL
            )
        ),
        ExerciseScreenSpacingPreviewCase(
            label = "Main deload",
            scenario = ExercisePreviewScenario(
                name = "main_deload",
                setType = ExercisePreviewSetType.WEIGHT,
                isUnilateral = true,
                progressionState = ProgressionState.DELOAD,
                includeBarbellPage = true,
                includeSupersetMetadata = true,
                previewSetCount = 3,
                openPage = ExercisePreviewPage.DETAIL
            )
        )
    )
}

@Preview(
    name = "Main Page Metadata",
    group = "ExerciseScreen/Spacing",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
private fun ExerciseScreenPreviewMainPageMetadata(
    @PreviewParameter(ExerciseScreenMainPageMetadataPreviewProvider::class, limit = 2)
    previewCase: ExerciseScreenSpacingPreviewCase
) {
    ExerciseScreenPreviewScenario(previewCase.scenario)
}
