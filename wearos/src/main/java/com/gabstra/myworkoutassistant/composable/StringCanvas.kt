package com.gabstra.myworkoutassistant.composable

import android.graphics.Typeface
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.wrapContentSize
import androidx.compose.foundation.layout.wrapContentWidth
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalFontFamilyResolver
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontSynthesis
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

@Composable
fun CharacterCanvas(
    char: Char,
    modifier: Modifier = Modifier,
    textStyle: TextStyle,
    textColor: Color = Color.White,
) {
    // 1. Risolvi la Typeface da TextStyle
    val resolver = LocalFontFamilyResolver.current
    val resolvedTypeface = remember(resolver, textStyle) {
        resolver.resolve(
            fontFamily = textStyle.fontFamily,
            fontWeight = textStyle.fontWeight ?: FontWeight.Normal,
            fontStyle = textStyle.fontStyle ?: FontStyle.Normal,
            fontSynthesis = textStyle.fontSynthesis ?: FontSynthesis.All
        )
    }.value as Typeface

    Canvas(modifier = modifier) {
        // 2. Prepara il Paint usando i valori di TextStyle
        val paint = android.graphics.Paint().apply {
            isAntiAlias = true
            color = textColor.toArgb()
            textAlign = android.graphics.Paint.Align.CENTER
            typeface = resolvedTypeface
            textSize = textStyle.fontSize.toPx()
        }

        // 3. Centra verticalmente e orizzontalmente
        val fm = paint.fontMetrics

        val x            = size.width  / 2f
        val y = (size.height - (fm.ascent + fm.descent)) / 2f

        drawContext.canvas.nativeCanvas.drawText(char.toString(), x, y, paint)
    }
}

@Composable
fun StringCanvas(
    text: String,
    modifier: Modifier = Modifier,
    charModifier: Modifier = Modifier,
    textStyle: TextStyle,
    textColor: Color = Color.White,
    textSpacing: Dp = 2.dp,
) {
    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(textSpacing)
    ) {
        text.forEach { c ->
            CharacterCanvas(
                char = c,
                modifier = charModifier,
                textStyle = textStyle,
                textColor = textColor
            )
        }
    }
}