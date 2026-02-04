package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material3.LocalTextStyle
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar

private const val DEFAULT_VISIBLE_LINES = 2.5f

/**
 * A vertically scrollable column that displays text with the same API as [Text].
 * The column has a maximum height of [maxLines] and a half lines (or [DEFAULT_VISIBLE_LINES] when
 * [maxLines] is [Int.MAX_VALUE]); it may be shorter when content fits in fewer lines.
 * Uses the custom vertical scrollbar.
 */
@Composable
fun ScrollableTextColumn(
    text: String,
    modifier: Modifier = Modifier,
    color: Color = Color.Unspecified,
    fontSize: TextUnit = TextUnit.Unspecified,
    fontStyle: FontStyle? = null,
    fontWeight: FontWeight? = null,
    fontFamily: FontFamily? = null,
    letterSpacing: TextUnit = TextUnit.Unspecified,
    textDecoration: TextDecoration? = null,
    textAlign: TextAlign? = null,
    lineHeight: TextUnit = TextUnit.Unspecified,
    overflow: TextOverflow = TextOverflow.Clip,
    softWrap: Boolean = true,
    maxLines: Int = Int.MAX_VALUE,
    minLines: Int = 1,
    onTextLayout: (androidx.compose.ui.text.TextLayoutResult) -> Unit = {},
    style: TextStyle? = null
) {
    val baseStyle = style ?: LocalTextStyle.current
    val effectiveStyle = baseStyle.copy(
        color = if (color != Color.Unspecified) color else baseStyle.color,
        fontSize = if (fontSize != TextUnit.Unspecified) fontSize else baseStyle.fontSize,
        fontStyle = fontStyle ?: baseStyle.fontStyle,
        fontWeight = fontWeight ?: baseStyle.fontWeight,
        fontFamily = fontFamily ?: baseStyle.fontFamily,
        letterSpacing = if (letterSpacing != TextUnit.Unspecified) letterSpacing else baseStyle.letterSpacing,
        textDecoration = textDecoration ?: baseStyle.textDecoration,
        textAlign = textAlign ?: baseStyle.textAlign,
        lineHeight = if (lineHeight != TextUnit.Unspecified) lineHeight else baseStyle.lineHeight
    )

    val resolvedLineHeight = when {
        effectiveStyle.lineHeight != TextUnit.Unspecified -> effectiveStyle.lineHeight
        effectiveStyle.fontSize != TextUnit.Unspecified -> effectiveStyle.fontSize * 1.5f
        else -> MaterialTheme.typography.bodyLarge.lineHeight
    }

    val visibleLines = if (maxLines == Int.MAX_VALUE) DEFAULT_VISIBLE_LINES else maxLines + 0.5f
    val heightDp = with(LocalDensity.current) {
        (resolvedLineHeight.value * visibleLines).sp.toDp()
    }

    val scrollState = rememberScrollState()
    Column(
        modifier = modifier
            .heightIn(max = heightDp)
            .verticalColumnScrollbar(scrollState = scrollState)
            .verticalScroll(scrollState)
    ) {
        Text(
            text = text,
            modifier = Modifier.fillMaxWidth(),
            color = color,
            fontSize = fontSize,
            fontStyle = fontStyle,
            fontWeight = fontWeight,
            fontFamily = fontFamily,
            letterSpacing = letterSpacing,
            textDecoration = textDecoration,
            textAlign = textAlign,
            lineHeight = lineHeight,
            overflow = overflow,
            softWrap = softWrap,
            maxLines = maxLines,
            minLines = minLines,
            onTextLayout = onTextLayout,
            style = style ?: LocalTextStyle.current
        )
    }
}
