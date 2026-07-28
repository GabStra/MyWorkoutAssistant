package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material3.Button
import androidx.wear.compose.material3.ButtonColors
import androidx.wear.compose.material3.ButtonDefaults
import androidx.wear.compose.material3.FilledTonalButton
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.SurfaceTransformation
import androidx.wear.compose.material3.Text

/**
 * Wear Material3 button roles (see `androidx.wear.compose.material3`). Prefer these over ad-hoc
 * [Button] / [FilledTonalButton] / [androidx.wear.compose.material3.OutlinedButton] so emphasis stays
 * consistent across screens.
 *
 * - **Primary (filled)** — [WearPrimaryButton] / [WearPrimaryContentButton]: main CTA (Start, Resume,
 *   confirm, list rows that are the primary tap target).
 * - **Secondary (tonal)** — [WearTonalButton] and [ButtonWithText]: lower emphasis than primary
 *   filled (Back, workout list rows when list item is not a strong CTA, optional actions).
 * - **Outlined** — [OutlinedButtonWithText]: use when a border is needed without filling the shape.
 *
 * On small round screens, avoid mixing multiple filled primaries in one glanceable column without
 * hierarchy—use tonal for the supporting action and filled for the one main action.
 */

@Composable
fun WearPrimaryButton(
    modifier: Modifier = Modifier,
    transformation: SurfaceTransformation? = null,
    text: String,
    enabled: Boolean = true,
    onClick: () -> Unit,
    colors: ButtonColors = ButtonDefaults.buttonColors(),
) {
    Button(
        modifier = modifier,
        transformation = transformation,
        enabled = enabled,
        onClick = onClick,
        colors = colors,
    ) {
        Text(
            modifier = Modifier.fillMaxWidth(),
            text = text,
            textAlign = TextAlign.Center,
            style = MaterialTheme.typography.bodyLarge,
        )
    }
}

@Composable
fun WearPrimaryContentButton(
    modifier: Modifier = Modifier,
    transformation: SurfaceTransformation? = null,
    enabled: Boolean = true,
    onClick: () -> Unit,
    colors: ButtonColors = ButtonDefaults.buttonColors(),
    content: @Composable RowScope.() -> Unit,
) {
    Button(
        modifier = modifier,
        transformation = transformation,
        enabled = enabled,
        onClick = onClick,
        colors = colors,
        content = content,
    )
}

@Composable
fun WearTonalButton(
    modifier: Modifier = Modifier,
    transformation: SurfaceTransformation? = null,
    text: String,
    enabled: Boolean = true,
    scaleTextToFit: Boolean = false,
    supportingText: String? = null,
    onClick: () -> Unit,
    colors: ButtonColors = ButtonDefaults.filledTonalButtonColors(),
) {
    FilledTonalButton(
        modifier = modifier,
        transformation = transformation,
        enabled = enabled,
        colors = colors,
        onClick = onClick,
    ) {
        if (scaleTextToFit) {
            val labelColor = if (enabled) {
                MaterialTheme.colorScheme.onSecondaryContainer
            } else {
                MaterialTheme.colorScheme.onSurface.copy(alpha = 0.38f)
            }
            Column(
                modifier = Modifier.fillMaxWidth(),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                ScalableText(
                    modifier = Modifier
                        .fillMaxWidth()
                        .height(20.dp),
                    text = text,
                    style = MaterialTheme.typography.labelMedium,
                    color = labelColor,
                    textAlign = TextAlign.Center,
                    minTextSize = 8.sp,
                )
                supportingText?.let {
                    Text(
                        text = it,
                        style = MaterialTheme.typography.labelSmall,
                        color = labelColor,
                        textAlign = TextAlign.Center,
                        maxLines = 1,
                    )
                }
            }
        } else {
            Text(
                modifier = Modifier.fillMaxWidth(),
                text = text,
                textAlign = TextAlign.Center,
            )
        }
    }
}
