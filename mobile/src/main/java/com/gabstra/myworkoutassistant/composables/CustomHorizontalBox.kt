package com.gabstra.myworkoutassistant.composables

import com.patrykandpatrick.vico.compose.cartesian.CartesianDrawingContext
import com.patrykandpatrick.vico.compose.cartesian.axis.Axis
import com.patrykandpatrick.vico.compose.cartesian.decoration.Decoration
import com.patrykandpatrick.vico.compose.cartesian.decoration.HorizontalBox
import com.patrykandpatrick.vico.compose.common.Position
import com.patrykandpatrick.vico.compose.common.component.ShapeComponent
import com.patrykandpatrick.vico.compose.common.component.TextComponent
import com.patrykandpatrick.vico.compose.common.data.ExtraStore
import java.text.DecimalFormat


public class CustomHorizontalBox(
    private val y: (ExtraStore) -> ClosedFloatingPointRange<Double>,
    private val box: ShapeComponent,
    private val labelComponent: TextComponent? = null,
    private val label: (ExtraStore) -> CharSequence = { getLabel(y(it)) },
    private val horizontalLabelPosition: Position.Horizontal = Position.Horizontal.Start,
    private val verticalLabelPosition: Position.Vertical = Position.Vertical.Top,
    private val labelRotationDegrees: Float = 0f,
    private val verticalAxisPosition: Axis.Position.Vertical? = null,
) : Decoration {
    override fun drawUnderLayers(context: CartesianDrawingContext) {
        with(context) {
            val horizontalBox = HorizontalBox(
                y = y,
                box = box,
                labelComponent = labelComponent,
                label = label,
                horizontalLabelPosition = horizontalLabelPosition,
                verticalLabelPosition = verticalLabelPosition,
                labelRotationDegrees = labelRotationDegrees,
                verticalAxisPosition = verticalAxisPosition,
            )

            horizontalBox.drawOverLayers(context)
        }
    }

    public companion object {
        private val decimalFormat = DecimalFormat("#.##;−#.##")

        public fun getLabel(y: ClosedFloatingPointRange<Double>): String =
            "${decimalFormat.format(y.start)}–${decimalFormat.format(y.endInclusive)}"
    }
}

