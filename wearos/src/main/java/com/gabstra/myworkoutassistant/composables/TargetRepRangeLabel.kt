package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.Composable
import com.gabstra.myworkoutassistant.presentation.theme.tertiaryContent
import androidx.compose.ui.text.style.TextAlign
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text

@Composable
internal fun TargetRepRangeLabel(targetRepRange: String) {
    Text(
        text = "TARGET REPS: $targetRepRange",
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.tertiaryContent,
        textAlign = TextAlign.Center,
        maxLines = 1,
    )
}
