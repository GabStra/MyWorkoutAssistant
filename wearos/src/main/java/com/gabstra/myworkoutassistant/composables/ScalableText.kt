package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.material3.LocalTextStyle
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.onGloballyPositioned
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material.Text
import com.gabstra.myworkoutassistant.shared.LightGray


@SuppressLint("UnusedBoxWithConstraintsScope")
@Composable
fun ScalableText(
    modifier: Modifier = Modifier,
    text: String,
    color: Color = LightGray,
    style: TextStyle = LocalTextStyle.current,
    textAlign: TextAlign? = null,
    minTextSize: TextUnit = 6.sp,
    contentAlignment: Alignment = Alignment.Center
) {
    var textSize by remember { mutableStateOf(style.fontSize) }
    var isScaling by remember { mutableStateOf(true) }
    var isTextVisible by remember { mutableStateOf(false) }
    val density = LocalDensity.current
    val textMeasurer = rememberTextMeasurer()

    val alphaValue by animateFloatAsState(
        targetValue = if (isTextVisible) 1f else 0f,
        animationSpec = tween(durationMillis = 300), label = ""
    )

    LaunchedEffect(isScaling) {
        isTextVisible = !isScaling
    }

    BoxWithConstraints(
        modifier = modifier.alpha(alphaValue),
        contentAlignment = contentAlignment
    ) {
        val boxWidth = maxWidth
        val boxHeight = maxHeight

        val textLayoutResult = textMeasurer.measure(
            text = text,
            style = style.copy(fontSize = textSize)
        )

        Text(
            text = text,
            style = style.copy(fontSize = textSize),
            maxLines = 1,
            color = color,
            textAlign = textAlign,
            modifier = Modifier.onGloballyPositioned { _ ->
                val textWidth = with(density) { textLayoutResult.size.width.toDp() }
                val textHeight = with(density) { textLayoutResult.size.height.toDp() }

                isScaling = textWidth > boxWidth || textHeight > boxHeight
            }
        )

        LaunchedEffect(isScaling) {
            while (isScaling) {
                textSize *= 0.9f
                val newTextLayoutResult = textMeasurer.measure(
                    text = text,
                    style = style.copy(fontSize = textSize)
                )
                val newTextWidth = with(density) { newTextLayoutResult.size.width.toDp() }
                val newTextHeight = with(density) { newTextLayoutResult.size.height.toDp() }

                if ((newTextWidth <= boxWidth && newTextHeight <= boxHeight) || textSize <= minTextSize) {
                    isScaling = false
                }
            }
        }
    }
}