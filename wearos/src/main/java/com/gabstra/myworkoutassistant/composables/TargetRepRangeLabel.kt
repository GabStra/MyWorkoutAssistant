package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.Composable
import com.gabstra.myworkoutassistant.presentation.theme.tertiaryContent
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.text.style.TextAlign
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.R

@Composable
internal fun TargetRepRangeLabel(targetRepRange: String) {
    Text(
        text = stringResource(R.string.components_target_reps, targetRepRange),
        style = MaterialTheme.typography.bodySmall,
        color = MaterialTheme.colorScheme.tertiaryContent,
        textAlign = TextAlign.Center,
        maxLines = 1,
    )
}
