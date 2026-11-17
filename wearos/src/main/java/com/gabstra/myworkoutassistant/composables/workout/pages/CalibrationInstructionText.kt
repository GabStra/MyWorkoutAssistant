package com.gabstra.myworkoutassistant.composables.workout.pages

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.BasicText
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.em
import androidx.wear.compose.material3.MaterialTheme

@Composable
internal fun CalibrationInstructionText(text: String, modifier: Modifier = Modifier, maxLines: Int = Int.MAX_VALUE) {
    val style = MaterialTheme.typography.bodyMedium
    BasicText(
        text = text,
        modifier = modifier.fillMaxWidth().padding(horizontal = 25.dp),
        style = style.copy(
            color = MaterialTheme.colorScheme.onSurfaceVariant,
            textAlign = TextAlign.Center,
            lineHeight = 1.1.em,
        ),
        maxLines = maxLines,
        softWrap = true,
    )
}
