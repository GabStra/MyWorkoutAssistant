package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.heightIn
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.DisabledContentGray

@Composable
fun AppPrimaryButton(
    modifier: Modifier = Modifier,
    text: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    minHeight: Dp = 48.dp
) {
    AppFilledButton(
        text = text,
        onClick = onClick,
        enabled = enabled,
        modifier = modifier,
        minHeight = minHeight,
        colors = ButtonDefaults.buttonColors(
            contentColor = MaterialTheme.colorScheme.background,
            disabledContainerColor = MaterialTheme.colorScheme.surfaceVariant.copy(alpha = 0.6f),
            disabledContentColor = DisabledContentGray
        ),
        enabledTextColor = MaterialTheme.colorScheme.onPrimary
    )
}

@Composable
fun AppPrimaryOutlinedButton(
    modifier: Modifier = Modifier,
    text: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    color: Color = MaterialTheme.colorScheme.primary,
    minHeight: Dp = 48.dp
) {
    OutlinedButton(
        onClick = onClick,
        enabled = enabled,
        modifier = Modifier.heightIn(min = minHeight).then(modifier),
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
            style = MaterialTheme.typography.bodyLarge
        )
    }
}

@Composable
fun AppSecondaryButton(
    modifier: Modifier = Modifier,
    text: String,
    onClick: () -> Unit,
    enabled: Boolean = true,
    minHeight: Dp = 48.dp
) {
    AppFilledButton(
        text = text,
        onClick = onClick,
        enabled = enabled,
        modifier = modifier,
        minHeight = minHeight,
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
private fun AppFilledButton(
    text: String,
    onClick: () -> Unit,
    enabled: Boolean,
    modifier: Modifier,
    minHeight: Dp,
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
            style = MaterialTheme.typography.bodyLarge
        )
    }
}
