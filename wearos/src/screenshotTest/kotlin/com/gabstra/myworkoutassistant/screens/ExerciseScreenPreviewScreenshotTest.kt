package com.gabstra.myworkoutassistant.screens

import androidx.compose.runtime.Composable
import androidx.compose.ui.tooling.preview.Preview
import androidx.wear.tooling.preview.devices.WearDevices
import com.android.tools.screenshot.PreviewTest

@PreviewTest
@Preview(
    name = "Weight Work Set",
    group = "ExerciseScreen/States",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
internal fun ExerciseScreenScreenshotWeightWorkSet() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "weight_work",
            setType = ExercisePreviewSetType.WEIGHT
        )
    )
}

@PreviewTest
@Preview(
    name = "Weight Warm-up Set",
    group = "ExerciseScreen/States",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
internal fun ExerciseScreenScreenshotWeightWarmup() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "weight_warmup",
            setType = ExercisePreviewSetType.WEIGHT,
            isWarmupSet = true
        )
    )
}

@PreviewTest
@Preview(
    name = "Calibration Confirmation Dialog",
    group = "ExerciseScreen/Dialog",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
internal fun ExerciseScreenScreenshotCalibrationDialog() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "calibration_dialog",
            setType = ExercisePreviewSetType.WEIGHT,
            isCalibrationSet = true,
            showConfirmationDialog = true
        )
    )
}

@PreviewTest
@Preview(
    name = "Auto-Regulation Confirmation Dialog",
    group = "ExerciseScreen/Dialog",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
internal fun ExerciseScreenScreenshotAutoRegulationDialog() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "auto_reg_dialog",
            setType = ExercisePreviewSetType.WEIGHT,
            isAutoRegulationWorkSet = true,
            showConfirmationDialog = true
        )
    )
}

@PreviewTest
@Preview(
    name = "Unilateral Switch Side Dialog",
    group = "ExerciseScreen/Dialog",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
internal fun ExerciseScreenScreenshotUnilateralDialog() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "unilateral_dialog",
            setType = ExercisePreviewSetType.WEIGHT,
            isUnilateral = true,
            intraSetCounter = 0u,
            showConfirmationDialog = true
        )
    )
}

@PreviewTest
@Preview(
    name = "Body Weight Set",
    group = "ExerciseScreen/States",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
internal fun ExerciseScreenScreenshotBodyWeight() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "body_weight",
            setType = ExercisePreviewSetType.BODY_WEIGHT
        )
    )
}

@PreviewTest
@Preview(
    name = "Timed Set Not Started",
    group = "ExerciseScreen/Timers",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
internal fun ExerciseScreenScreenshotTimedNotStarted() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "timed_not_started",
            setType = ExercisePreviewSetType.TIMED_DURATION
        )
    )
}

@PreviewTest
@Preview(
    name = "Timed Set Running",
    group = "ExerciseScreen/Timers",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
internal fun ExerciseScreenScreenshotTimedRunning() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "timed_running",
            setType = ExercisePreviewSetType.TIMED_DURATION,
            timedIsRunning = true
        )
    )
}

@PreviewTest
@Preview(
    name = "Endurance Set Over Limit",
    group = "ExerciseScreen/Timers",
    device = WearDevices.LARGE_ROUND,
    showBackground = true
)
@Composable
internal fun ExerciseScreenScreenshotEnduranceOverLimit() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "endurance_over_limit",
            setType = ExercisePreviewSetType.ENDURANCE,
            enduranceOverLimit = true
        )
    )
}

@PreviewTest
@Preview(
    name = "Buttons Page",
    group = "ExerciseScreen/Pages",
    device = WearDevices.SMALL_ROUND,
    showBackground = true
)
@Composable
internal fun ExerciseScreenScreenshotButtonsPage() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "buttons_page",
            setType = ExercisePreviewSetType.WEIGHT,
            openPageIndex = 0
        )
    )
}

@PreviewTest
@Preview(
    name = "Plates Page",
    group = "ExerciseScreen/Pages",
    device = WearDevices.SMALL_ROUND,
    showBackground = true
)
@Composable
internal fun ExerciseScreenScreenshotPlatesPage() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "plates_page",
            setType = ExercisePreviewSetType.WEIGHT,
            includeBarbellPage = true,
            openPageIndex = 1
        )
    )
}

@PreviewTest
@Preview(
    name = "Titled Lines Page",
    group = "ExerciseScreen/Pages",
    device = WearDevices.SMALL_ROUND,
    showBackground = true
)
@Composable
internal fun ExerciseScreenScreenshotTitledLinesPage() {
    ExerciseScreenPreviewScenario(
        ExercisePreviewScenario(
            name = "titled_lines_page",
            setType = ExercisePreviewSetType.WEIGHT,
            includeBarbellPage = true,
            includeTitledLinesPage = true,
            openPageIndex = 3
        )
    )
}
