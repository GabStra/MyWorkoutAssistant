package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupPositionProvider
import androidx.compose.ui.window.PopupProperties
import com.gabstra.myworkoutassistant.composables.AppDropdownMenuItem

data class MenuItem(
    val label: String,
    val onClick: () -> Unit
)

@Composable
fun GenericButtonWithMenu(
    menuItems: List<MenuItem>,
    content: @Composable () -> Unit,
    enabled: Boolean = true
) {
    var expanded by remember { mutableStateOf(false) }
    val density = LocalDensity.current
    val popupPositionProvider = remember(density) {
        TopCenterMenuPositionProvider(
            verticalMarginPx = with(density) { 4.dp.roundToPx() }
        )
    }

    Box(
        modifier = Modifier
            .fillMaxWidth(),
        contentAlignment = Alignment.Center
    ) {
        Box {
            Button(
                colors = ButtonDefaults.buttonColors(
                    contentColor = MaterialTheme.colorScheme.background,
                    disabledContentColor = MaterialTheme.colorScheme.onSurfaceVariant
                ),
                onClick = { expanded = !expanded },
                enabled = enabled
            ) { content() }

            if (expanded) {
                Popup(
                    popupPositionProvider = popupPositionProvider,
                    onDismissRequest = { expanded = false },
                    properties = PopupProperties(focusable = true)
                ) {
                    MenuSurface {
                        Column {
                            menuItems.forEach { item ->
                                AppDropdownMenuItem(
                                    onClick = {
                                        item.onClick()
                                        expanded = false
                                    },
                                    text = { Text(item.label) }
                                )
                            }
                        }
                    }
                }
            }
        }
    }
}

private class TopCenterMenuPositionProvider(
    private val verticalMarginPx: Int
) : PopupPositionProvider {
    override fun calculatePosition(
        anchorBounds: IntRect,
        windowSize: IntSize,
        layoutDirection: LayoutDirection,
        popupContentSize: IntSize
    ): IntOffset {
        val popupWidth = popupContentSize.width
        val popupHeight = popupContentSize.height
        val maxX = (windowSize.width - popupWidth).coerceAtLeast(0)
        val maxY = (windowSize.height - popupHeight).coerceAtLeast(0)

        val centeredX = anchorBounds.left + (anchorBounds.width - popupWidth) / 2
        val aboveY = anchorBounds.top - popupHeight - verticalMarginPx
        val belowY = anchorBounds.bottom + verticalMarginPx
        val resolvedY = if (aboveY >= 0) aboveY else belowY

        return IntOffset(
            x = centeredX.coerceIn(0, maxX),
            y = resolvedY.coerceIn(0, maxY)
        )
    }
}
