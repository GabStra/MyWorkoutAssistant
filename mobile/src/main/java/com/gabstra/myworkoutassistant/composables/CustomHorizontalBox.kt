package com.gabstra.myworkoutassistant.composables

import android.graphics.RectF
import androidx.annotation.RestrictTo
import com.patrykandpatrick.vico.core.cartesian.CartesianDrawingContext
import com.patrykandpatrick.vico.core.cartesian.axis.Axis
import com.patrykandpatrick.vico.core.cartesian.decoration.Decoration
import com.patrykandpatrick.vico.core.cartesian.decoration.HorizontalBox
import com.patrykandpatrick.vico.core.common.Position
import com.patrykandpatrick.vico.core.common.component.ShapeComponent
import com.patrykandpatrick.vico.core.common.component.TextComponent
import com.patrykandpatrick.vico.core.common.data.ExtraStore
import com.patrykandpatrick.vico.core.common.half
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