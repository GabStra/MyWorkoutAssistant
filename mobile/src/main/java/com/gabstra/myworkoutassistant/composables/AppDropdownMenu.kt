package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.BorderStroke
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.RectangleShape
import androidx.compose.ui.unit.DpOffset
import androidx.compose.ui.unit.dp

@Composable
fun AppDropdownMenu(
    expanded: Boolean,
    onDismissRequest: () -> Unit,
    modifier: Modifier = Modifier,
    offset: DpOffset = DpOffset(0.dp, 0.dp),
    content: @Composable ColumnScope.() -> Unit
) {
    val borderColor = MaterialTheme.colorScheme.outlineVariant
    DropdownMenu(
        expanded = expanded,
        onDismissRequest = onDismissRequest,
        modifier = modifier,
        offset = offset,
        shape = RectangleShape,
        containerColor = MaterialTheme.colorScheme.surfaceVariant,
        tonalElevation = 0.dp,
        shadowElevation = 4.dp,
        border = BorderStroke(1.dp, borderColor),
    ) {
        AppMenuContent {
            content()
        }
    }
}

@Composable
fun ColumnScope.AppMenuContent(content: @Composable ColumnScope.() -> Unit) {
    CompositionLocalProvider(
        LocalContentColor provides MaterialTheme.colorScheme.onSurface,
        LocalTextStyle provides MaterialTheme.typography.bodyLarge.copy(
            fontWeight = androidx.compose.ui.text.font.FontWeight.Medium
        )
    ) {
        content()
    }
}

@Composable
fun MenuSurface(
    modifier: Modifier = Modifier,
    content: @Composable () -> Unit
) {
    val borderColor = MaterialTheme.colorScheme.outlineVariant
    Surface(
        modifier = modifier,
        shape = RectangleShape,
        color = MaterialTheme.colorScheme.surfaceVariant,
        tonalElevation = 0.dp,
        shadowElevation = 4.dp,
        border = BorderStroke(1.dp, borderColor),
    ) {
        CompositionLocalProvider(
            LocalContentColor provides MaterialTheme.colorScheme.onSurface,
            LocalTextStyle provides MaterialTheme.typography.bodyLarge.copy(
                fontWeight = androidx.compose.ui.text.font.FontWeight.Medium
            )
        ) {
            content()
        }
    }
}

@Composable
fun AppDropdownMenuItem(
    text: @Composable () -> Unit,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    leadingIcon: (@Composable () -> Unit)? = null,
    trailingIcon: (@Composable () -> Unit)? = null,
    enabled: Boolean = true
) {
    val baseColor = MaterialTheme.colorScheme.onSurface
    val contentColor = if (enabled) baseColor else MaterialTheme.colorScheme.onSurfaceVariant

    fun wrapContent(content: @Composable () -> Unit): @Composable () -> Unit = {
        CompositionLocalProvider(LocalContentColor provides contentColor) {
            content()
        }
    }

    DropdownMenuItem(
        text = wrapContent(text),
        onClick = onClick,
        modifier = modifier,
        leadingIcon = leadingIcon?.let { wrapContent(it) },
        trailingIcon = trailingIcon?.let { wrapContent(it) },
        enabled = enabled
    )
}
