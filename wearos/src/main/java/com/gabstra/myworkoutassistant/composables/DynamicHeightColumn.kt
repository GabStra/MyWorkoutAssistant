package com.gabstra.myworkoutassistant.composables

import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.layout.SubcomposeLayout

/**
 * A layout that fills the maximum available height with a dimension that is a
 * multiple of its item's height.
 *
 * @param modifier The modifier to be applied to the layout.
 * @param prototypeItem A composable lambda that represents a single item to be used for measurement.
 * @param content The actual content to be displayed within the calculated bounds, typically a Column.
 */
@Composable
fun DynamicHeightColumn(
    modifier: Modifier = Modifier,
    prototypeItem: @Composable () -> Unit,
    content: @Composable () -> Unit
) {
    SubcomposeLayout(modifier = modifier) { constraints ->
        // 1. Subcompose the prototype to measure it.
        val itemPlaceable = subcompose("prototype", prototypeItem).first().measure(
            constraints.copy(minHeight = 0)
        )
        val itemHeight = itemPlaceable.height

        // Avoid division by zero.
        if (itemHeight == 0) {
            return@SubcomposeLayout layout(constraints.minWidth, constraints.minHeight) {}
        }

        // 2. Calculate how many full items can fit in the available space.
        val maxItems = constraints.maxHeight / itemHeight

        // 3. Calculate the final height for the Column.
        val columnHeight = maxItems * itemHeight

        // 4. Subcompose the actual content with the exact calculated height.
        val contentPlaceable = subcompose("content", content)
            .first()
            .measure(
                constraints.copy(
                    minHeight = columnHeight,
                    maxHeight = columnHeight
                )
            )

        // 5. Set the layout size and place the content.
        layout(contentPlaceable.width, columnHeight) {
            contentPlaceable.placeRelative(0, 0)
        }
    }
}