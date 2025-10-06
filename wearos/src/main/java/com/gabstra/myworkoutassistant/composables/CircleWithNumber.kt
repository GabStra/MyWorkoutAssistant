

import android.annotation.SuppressLint
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.absoluteOffset
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.MaterialTheme
import com.gabstra.myworkoutassistant.composables.ScalableText
import kotlin.math.cos
import kotlin.math.sin


@SuppressLint("UnusedBoxWithConstraintsScope")
@Composable
fun CircleWithNumber(
    baseAngleInDegrees: Float,
    circleRadius: Float,
    circleColor: Color,
    number: Int,
    transparency: Float = 1f
) {
    val density = LocalDensity.current.density

    BoxWithConstraints(
        modifier = Modifier.fillMaxSize()
    ) {
        val boxWidth = (constraints.maxWidth/density).dp
        val boxHeight = (constraints.maxHeight/density).dp

        val angleInRadians = Math.toRadians(baseAngleInDegrees.toDouble())


        val widthOffset = (constraints.maxWidth/2) - 5
        val heightOffset = (constraints.maxHeight/2) - 5

        val xRadius = ((widthOffset * cos(angleInRadians)) / density).dp
        val yRadius = ((heightOffset * sin(angleInRadians)) / density).dp

        Box(
            modifier = Modifier
                .fillMaxSize()
                .absoluteOffset(
                    x = (boxWidth/2) - (circleRadius / density).dp + xRadius,
                    y = (boxHeight/2) - (circleRadius / density).dp + yRadius,
                ),
        ) {
            Canvas(modifier = Modifier.size((circleRadius * 2 / density).dp)) {
                drawCircle(
                    color = circleColor,
                    radius = (circleRadius / density).dp.toPx(),
                    center = center
                )
                drawCircle(
                    color = Color.Black,
                    radius = (circleRadius / density).dp.toPx(),
                    center = center,
                    style = Stroke(width = 3.dp.toPx())
                )
            }
            Box(modifier = Modifier
                .size((circleRadius * 2 / density).dp)
                .alpha(transparency)
                //.background(circleColor, CircleShape),
            ){
                ScalableText(
                    modifier = Modifier
                        .fillMaxSize()
                        .padding(3.dp),
                    text = number.toString(),
                    style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Bold),
                    textAlign = TextAlign.Center,
                )
            }
        }
    }



}