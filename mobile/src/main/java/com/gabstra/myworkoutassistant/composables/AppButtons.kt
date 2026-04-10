package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilledTonalButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.DisabledContentGray
import com.gabstra.myworkoutassistant.shared.Red

/**
 * App-wide button styles (Material 3 emphasis). Prefer these over raw [Button], [TextButton], etc.,
 * so disabled colors and typography stay consistent.
 *
 * - **Primary** — [AppPrimaryButton]: one main action per region (Save, Continue, filled CTA).
 * - **Secondary (filled)** — [AppSecondaryButton]: neutral filled; use sparingly when a second filled
 *   control is required.
 * - **Secondary (medium)** — [AppFilledTonalButton]: medium emphasis without a strong outline.
 * - **Outlined** — [AppPrimaryOutlinedButton]: alternate paths, optional actions, visible boundary.
 * - **Tertiary** — [AppTextButton]: Cancel, Clear, Show/Hide; does not compete with a filled primary.
 * - **Destructive** — [AppDestructiveButton] / [AppDeleteButton]: destructive confirm vs outlined red.
 */

@Composable
fun AppPrimaryButton(
    modifier: Modifier = Modifier,
    text: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    minHeight: Dp = 48.dp,
    textAlign: TextAlign = TextAlign.Start
) {
    AppFilledButton(
        text = text,
        onClick = onClick,
        enabled = enabled,
        modifier = modifier,
        minHeight = minHeight,
        textAlign = textAlign,
        colors = ButtonDefaults.buttonColors(
            contentColor = MaterialTheme.colorScheme.background,
            disabledContainerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
            disabledContentColor = DisabledContentGray
        ),
        enabledTextColor = MaterialTheme.colorScheme.onPrimary
    )
}

/**
 * Filled primary [Button] with custom content (e.g. menu anchor). Matches [AppPrimaryButton] colors.
 */
@Composable
fun AppPrimaryContentButton(
    modifier: Modifier = Modifier,
    onClick: () -> Unit,
    enabled: Boolean = true,
    minHeight: Dp = 48.dp,
    content: @Composable RowScope.() -> Unit
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = minHeight),
        colors = ButtonDefaults.buttonColors(
            contentColor = MaterialTheme.colorScheme.background,
            disabledContainerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
            disabledContentColor = DisabledContentGray
        )
    ) {
        content()
    }
}

@Composable
fun AppPrimaryOutlinedButton(
    modifier: Modifier = Modifier,
    text: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    color: Color = MaterialTheme.colorScheme.primary,
    minHeight: Dp = 48.dp,
    textAlign: TextAlign = TextAlign.Start
) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = minHeight),
        colors = ButtonDefaults.outlinedButtonColors(
            contentColor = color,
            disabledContentColor = DisabledContentGray
        ),
        border = BorderStroke(
            width =  1.0.dp,
            color =
                if (enabled) {
                    color
                } else {
                    DisabledContentGray
                },
        )
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.bodyLarge,
            textAlign = textAlign,
            modifier = Modifier.fillMaxWidthIfCentered(textAlign)
        )
    }
}

@Composable
fun AppSecondaryButton(
    modifier: Modifier = Modifier,
    text: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    minHeight: Dp = 48.dp,
    textAlign: TextAlign = TextAlign.Start
) {
    AppFilledButton(
        text = text,
        onClick = onClick,
        enabled = enabled,
        modifier = modifier,
        minHeight = minHeight,
        textAlign = textAlign,
        colors = ButtonDefaults.buttonColors(
            containerColor = MaterialTheme.colorScheme.surfaceVariant,
            contentColor = MaterialTheme.colorScheme.onBackground,
            disabledContainerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
            disabledContentColor = DisabledContentGray
        ),
        enabledTextColor = MaterialTheme.colorScheme.onBackground
    )
}

@Composable
fun AppFilledTonalButton(
    modifier: Modifier = Modifier,
    text: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    minHeight: Dp = 48.dp,
    textAlign: TextAlign = TextAlign.Start
) {
    FilledTonalButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = minHeight),
        colors = ButtonDefaults.filledTonalButtonColors(
            disabledContainerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
            disabledContentColor = DisabledContentGray
        )
    ) {
        Text(
            text = text,
            color = if (enabled) MaterialTheme.colorScheme.onSecondaryContainer else DisabledContentGray,
            style = MaterialTheme.typography.bodyLarge,
            textAlign = textAlign,
            modifier = Modifier.fillMaxWidthIfCentered(textAlign)
        )
    }
}

@Composable
fun AppTextButton(
    modifier: Modifier = Modifier,
    text: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    minHeight: Dp = 48.dp
) {
    TextButton(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = minHeight),
        colors = ButtonDefaults.textButtonColors(
            contentColor = MaterialTheme.colorScheme.primary,
            disabledContentColor = DisabledContentGray
        )
    ) {
        Text(
            text = text,
            style = MaterialTheme.typography.bodyLarge
        )
    }
}

@Composable
fun AppDestructiveButton(
    modifier: Modifier = Modifier,
    text: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    minHeight: Dp = 48.dp,
    textAlign: TextAlign = TextAlign.Start
) {
    AppFilledButton(
        text = text,
        onClick = onClick,
        enabled = enabled,
        modifier = modifier,
        minHeight = minHeight,
        textAlign = textAlign,
        colors = ButtonDefaults.buttonColors(
            containerColor = Red,
            contentColor = MaterialTheme.colorScheme.onError,
            disabledContainerColor = Red.copy(alpha = 0.5f),
            disabledContentColor = DisabledContentGray
        ),
        enabledTextColor = MaterialTheme.colorScheme.onError
    )
}

@Composable
fun AppDeleteButton(
    modifier: Modifier = Modifier,
    text: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    minHeight: Dp = 48.dp,
    textAlign: TextAlign = TextAlign.Start
) {
    AppPrimaryOutlinedButton(
        modifier = modifier,
        text = text,
        onClick = onClick,
        enabled = enabled,
        color = Red,
        minHeight = minHeight,
        textAlign = textAlign
    )
}

@Composable
private fun AppFilledButton(
    text: String,
    onClick: () -> Unit,
    enabled: Boolean,
    modifier: Modifier,
    minHeight: Dp,
    textAlign: TextAlign,
    colors: androidx.compose.material3.ButtonColors,
    enabledTextColor: androidx.compose.ui.graphics.Color
) {
    Button(
        onClick = onClick,
        enabled = enabled,
        modifier = modifier.heightIn(min = minHeight),
        colors = colors
    ) {
        Text(
            text = text,
            color = if (enabled) enabledTextColor else DisabledContentGray,
            style = MaterialTheme.typography.bodyLarge,
            textAlign = textAlign,
            modifier = Modifier.fillMaxWidthIfCentered(textAlign)
        )
    }
}

private fun Modifier.fillMaxWidthIfCentered(textAlign: TextAlign): Modifier =
    if (textAlign == TextAlign.Center) fillMaxWidth() else this
