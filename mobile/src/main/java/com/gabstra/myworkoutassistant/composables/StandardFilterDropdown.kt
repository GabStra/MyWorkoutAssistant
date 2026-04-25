package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.Check
import androidx.compose.material.icons.filled.ExpandMore
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
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

data class StandardFilterDropdownItem<T>(
    val value: T,
    val label: String
)

@Composable
fun <T> StandardFilterDropdown(
    label: String,
    selectedText: String,
    items: List<StandardFilterDropdownItem<T>>,
    onItemSelected: (T) -> Unit,
    modifier: Modifier = Modifier,
    isItemSelected: (T) -> Boolean = { false },
    enabled: Boolean = true
) {
    var expanded by remember { mutableStateOf(false) }
    val scrollState = rememberScrollState()
    val configuration = LocalConfiguration.current
    val density = LocalDensity.current
    val fieldTextStyle = MaterialTheme.typography.bodyLarge
    val maxPopupWidth = (configuration.screenWidthDp.dp - 32.dp).coerceAtLeast(160.dp)
    val popupPositionProvider = remember(density) {
        FilterMenuPositionProvider(
            verticalMarginPx = with(density) { 4.dp.roundToPx() }
        )
    }

    Box(modifier = modifier) {
        Box(modifier = Modifier.fillMaxWidth()) {
            OutlinedTextField(
                value = selectedText,
                onValueChange = { },
                readOnly = true,
                enabled = enabled,
                singleLine = true,
                textStyle = fieldTextStyle.copy(color = Color.Transparent),
                label = {
                    Text(
                        text = label,
                        style = MaterialTheme.typography.labelLarge
                    )
                },
                trailingIcon = {
                    Icon(
                        imageVector = Icons.Default.ExpandMore,
                        contentDescription = null
                    )
                },
                modifier = Modifier.fillMaxWidth()
            )

            Text(
                text = selectedText,
                style = fieldTextStyle,
                maxLines = 1,
                modifier = Modifier
                    .align(Alignment.CenterStart)
                    .padding(start = 16.dp, top = 6.dp, end = 48.dp)
                    .basicMarquee(iterations = Int.MAX_VALUE)
            )

            Box(
                modifier = Modifier
                    .matchParentSize()
                    .clickable(enabled = enabled) { expanded = true }
            )

            if (expanded) {
                Popup(
                    popupPositionProvider = popupPositionProvider,
                    onDismissRequest = { expanded = false },
                    properties = PopupProperties(focusable = true)
                ) {
                    MenuSurface(
                        modifier = Modifier.fillMaxWidth()
                    ) {
                        Column(
                            modifier = Modifier
                                .width(IntrinsicSize.Max)
                                .heightIn(max = 320.dp)
                                .verticalScroll(scrollState)
                        ) {
                            items.forEachIndexed { index, item ->
                                val selected = isItemSelected(item.value)

                                Row(
                                    modifier = Modifier
                                        .fillMaxWidth()
                                        .clickable {
                                            onItemSelected(item.value)
                                            expanded = false
                                        }
                                        .padding(horizontal = 16.dp, vertical = 12.dp),
                                    verticalAlignment = Alignment.CenterVertically
                                ) {
                                    Text(
                                        maxLines = 1,
                                        modifier = Modifier
                                            .weight(1f)
                                            .basicMarquee(iterations = Int.MAX_VALUE),
                                        text = item.label,
                                        fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal
                                    )
                                    if (selected) {
                                        Icon(
                                            imageVector = Icons.Default.Check,
                                            contentDescription = null
                                        )
                                    }
                                }

                                if (index < items.lastIndex) {
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

private class FilterMenuPositionProvider(
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
        val belowY = anchorBounds.bottom + verticalMarginPx
        val aboveY = anchorBounds.top - popupHeight - verticalMarginPx
        val resolvedY = if (belowY <= maxY) belowY else aboveY

        return IntOffset(
            x = centeredX.coerceIn(0, maxX),
            y = resolvedY.coerceIn(0, maxY)
        )
    }
}
