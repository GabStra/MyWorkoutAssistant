// ButtonWithText.kt
package com.gabstra.myworkoutassistant.workout

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.material3.Button
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.minimumInteractiveComponentSize
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp

enum class AppButtonStyle { Filled, Tonal, Outlined }

@Composable
fun ButtonWithText(
    modifier: Modifier = Modifier,
    text: String,
    enabled: Boolean = true,
    onClick: () -> Unit,
    style: AppButtonStyle = AppButtonStyle.Filled
) {



    val baseModifier = modifier
        .fillMaxWidth()
        // Ensure min 48.dp touch target (M3 recommendation)
        .minimumInteractiveComponentSize()
        .heightIn(min = 48.dp)

    val content: @Composable () -> Unit = {
        Text(
            modifier = Modifier.fillMaxWidth(),
            text = text,
            style = MaterialTheme.typography.titleMedium,
            textAlign = TextAlign.Center
        )
    }

    when (style) {
        AppButtonStyle.Filled -> Button(
            modifier = baseModifier,
            enabled = enabled,
            onClick = onClick
        ) { content() }

        AppButtonStyle.Tonal -> FilledTonalButton(
            modifier = baseModifier,
            enabled = enabled,
            onClick = onClick
        ) { content() }

        AppButtonStyle.Outlined -> OutlinedButton(
            modifier = baseModifier,
            enabled = enabled,
            onClick = onClick
        ) { content() }
    }
}

