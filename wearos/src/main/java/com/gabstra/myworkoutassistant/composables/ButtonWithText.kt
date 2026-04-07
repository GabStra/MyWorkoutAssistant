package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.wear.compose.material3.ButtonColors
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.OutlinedButton
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text

/**
 * Tonal filled label button — see [WearTonalButton] and the matrix in [WearAppButtons].
 */
@Composable
fun ButtonWithText(
    modifier: Modifier = Modifier,
    transformation: SurfaceTransformation? = null,
    text: String,
    enabled: Boolean = true,
    colors: ButtonColors = ButtonDefaults.filledTonalButtonColors(),
    onClick: () -> Unit
) {
    WearTonalButton(
        modifier = modifier,
        transformation = transformation,
        text = text,
        enabled = enabled,
        colors = colors,
        onClick = onClick,
    )
}

@Composable
fun OutlinedButtonWithText(
    modifier: Modifier = Modifier,
    transformation: SurfaceTransformation? = null,
    text: String,
    enabled: Boolean = true,
    borderColor: Color? = null,
    textColor: Color? = null,
    onClick: () -> Unit
) {
    OutlinedButton(
        modifier = modifier,
        transformation = transformation,
        enabled = enabled,
        border = borderColor?.let {
            ButtonDefaults.outlinedButtonBorder(
                enabled = enabled,
                borderColor = it
            )
        } ?: ButtonDefaults.outlinedButtonBorder(enabled = enabled),
        onClick = onClick
    ) {
        Text(
            modifier = Modifier.fillMaxWidth(),
            text = text,
            textAlign = TextAlign.Center,
            color = textColor ?: MaterialTheme.colorScheme.onSurface
        )
    }
}

@Composable
fun CancelButtonWithText(
    modifier: Modifier = Modifier,
    transformation: SurfaceTransformation? = null,
    text: String,
    enabled: Boolean = true,
    onClick: () -> Unit
) {
    ButtonWithText(
        modifier = modifier,
        transformation = transformation,
        text = text,
        enabled = enabled,
        onClick = onClick
    )
}
