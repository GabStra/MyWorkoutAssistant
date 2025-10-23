package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.runtime.Composable
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.wear.compose.material3.LocalTextStyle
import androidx.wear.compose.material3.MaterialTheme

@Composable
fun OutlinedScalableText(
    text: String,
    modifier: Modifier = Modifier,
    style: TextStyle = LocalTextStyle.current,
    textAlign: TextAlign? = TextAlign.Center,
    fill: Color = MaterialTheme.colorScheme.onBackground,
    outline: Color = Color.Black,
    outlineWidth: Dp = 1.dp,
    contentAlignment: Alignment = Alignment.Center
) {
    val density = LocalDensity.current
    val px = with(density) { outlineWidth.toPx() }

    Box(modifier = modifier.padding(outlineWidth), contentAlignment = contentAlignment) {
        ScalableText(
            text = text,
            style = style.copy(drawStyle = androidx.compose.ui.graphics.drawscope.Stroke(width = px)),
            textAlign = TextAlign.Center,
            color = outline
        )
        // Fill (top)
        ScalableText(
            text = text,
            style = style,
            textAlign = textAlign,
            color = fill
        )
    }
}
