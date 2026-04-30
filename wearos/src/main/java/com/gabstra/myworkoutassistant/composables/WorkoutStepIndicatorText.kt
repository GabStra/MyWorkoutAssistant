package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text

@Composable
fun WorkoutStepIndicatorText(
    stepLabel: String?,
    modifier: Modifier = Modifier,
) {
    if (stepLabel.isNullOrBlank()) return

    Text(
        text = stepLabel,
        modifier = modifier,
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.onSurfaceVariant
    )
}
