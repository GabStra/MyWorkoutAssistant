package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalConfiguration
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.IntRect
import androidx.compose.ui.unit.IntSize
import androidx.compose.ui.unit.LayoutDirection
import androidx.compose.ui.unit.dp
import androidx.compose.ui.window.Popup
import androidx.compose.ui.window.PopupPositionProvider
import androidx.compose.ui.window.PopupProperties

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
    val scrollState = rememberScrollState()
    val configuration = LocalConfiguration.current
    val density = LocalDensity.current
    val maxPopupWidth = (configuration.screenWidthDp.dp - 32.dp).coerceAtLeast(160.dp)
    val popupPositionProvider = remember(density) {
        TopCenterMenuPositionProvider(
            verticalMarginPx = with(density) { 4.dp.roundToPx() }
        )
    }

    Box(
        contentAlignment = Alignment.Center
    ) {
        Box {
            AppPrimaryContentButton(
                onClick = { expanded = !expanded },
                enabled = enabled
            ) { content() }

            if (expanded) {
                Popup(
                    popupPositionProvider = popupPositionProvider,
                    onDismissRequest = { expanded = false },
                    properties = PopupProperties(focusable = true)
                ) {
                    MenuSurface(
                        modifier = Modifier.widthIn(
                            max = maxPopupWidth
                        )
                    ) {
                        Column(
                            modifier = Modifier
                                .width(IntrinsicSize.Max)
                                .heightIn(max = 240.dp)
                                .verticalScroll(scrollState)
                        ) {
                            menuItems.forEachIndexed { index, item ->
                                Text(
                                    text = item.label,
                                    fontWeight = FontWeight.Normal,
                                    maxLines = 1,
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .basicMarquee(iterations = Int.MAX_VALUE)
                                        .clickable {
                                            item.onClick()
                                            expanded = false
                                        }
                                        .padding(horizontal = 16.dp, vertical = 12.dp)
                                )
                                if (index < menuItems.lastIndex) {
                                    HorizontalDivider(
                                        color = appMenuBorderColor()
                                    )
                                }
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
