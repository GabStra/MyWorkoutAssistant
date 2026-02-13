package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.LocalContentColor
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Surface
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.DpOffset
import androidx.compose.ui.unit.dp
import com.gabstra.myworkoutassistant.shared.DarkGray
import com.gabstra.myworkoutassistant.shared.DisabledContentGray

@Composable
fun AppDropdownMenu(
    expanded: Boolean,
    onDismissRequest: () -> Unit,
    modifier: Modifier = Modifier,
    offset: DpOffset = DpOffset(0.dp, 0.dp),
    content: @Composable ColumnScope.() -> Unit
) {
    DropdownMenu(
        expanded = expanded,
        onDismissRequest = onDismissRequest,
        modifier = modifier,
        offset = offset,
        shape = RoundedCornerShape(4.dp),
        containerColor = DarkGray,
        tonalElevation = 0.dp,
        shadowElevation = 4.dp,
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
    Surface(
        modifier = modifier,
        shape = RoundedCornerShape(4.dp),
        color = DarkGray,
        tonalElevation = 0.dp,
        shadowElevation = 4.dp,
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
    val contentColor = if (enabled) baseColor else DisabledContentGray

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
