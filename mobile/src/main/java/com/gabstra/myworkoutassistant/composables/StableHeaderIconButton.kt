package com.gabstra.myworkoutassistant.composables

import androidx.compose.material3.IconButton
import androidx.compose.material3.IconButtonColors
import androidx.compose.material3.IconButtonDefaults
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.semantics.clearAndSetSemantics

@Composable
fun StableHeaderIconButton(
    visible: Boolean,
    onClick: () -> Unit,
    modifier: Modifier = Modifier,
    enabled: Boolean = visible,
    colors: IconButtonColors = IconButtonDefaults.iconButtonColors(),
    content: @Composable () -> Unit,
) {
    if(!visible) return

    IconButton(
        onClick = onClick,
        enabled = enabled,
        colors = colors,
        modifier = modifier
            .alpha(if (enabled) 1f else 0f)
            .then(if (enabled) Modifier else Modifier.clearAndSetSemantics { })
    ) {
        content()
    }
}
