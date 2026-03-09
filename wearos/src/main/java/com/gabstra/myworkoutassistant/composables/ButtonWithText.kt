package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.wear.compose.material3.ButtonColors
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.FilledTonalButton
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text

@Composable
fun ButtonWithText(
    modifier: Modifier = Modifier,
    transformation: SurfaceTransformation? = null,
    text: String,
    enabled: Boolean = true,
    colors: ButtonColors = ButtonDefaults.filledTonalButtonColors(),
    onClick: () -> Unit
) {
    FilledTonalButton(
        modifier = modifier,
        transformation = transformation,
        enabled = enabled,
        colors = colors,
        onClick = onClick,
    ) {
        Text(
            modifier = Modifier.fillMaxWidth(),
            text = text,
            textAlign = TextAlign.Center,
        )
    }
}
