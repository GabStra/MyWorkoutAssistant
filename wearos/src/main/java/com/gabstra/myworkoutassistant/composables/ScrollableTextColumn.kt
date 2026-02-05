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
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.tooling.preview.Preview
import androidx.compose.ui.unit.TextUnit
import androidx.compose.ui.unit.sp
import androidx.wear.compose.material3.LocalTextConfiguration
import androidx.wear.compose.material3.LocalTextStyle
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import androidx.wear.tooling.preview.devices.WearDevices
import com.gabstra.myworkoutassistant.data.verticalColumnScrollbar
import com.gabstra.myworkoutassistant.presentation.theme.baseline
import com.gabstra.myworkoutassistant.presentation.theme.darkScheme

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
    maxLines: Int = Int.MAX_VALUE,
    textAlign: TextAlign? = LocalTextConfiguration.current.textAlign,
    style: TextStyle? = null
) {
    val baseStyle = style ?: LocalTextStyle.current

    val resolvedLineHeight = when {
        baseStyle.lineHeight != TextUnit.Unspecified -> baseStyle.lineHeight
        baseStyle.fontSize != TextUnit.Unspecified -> baseStyle.fontSize * 1.5f
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
            .verticalScroll(state = scrollState)
    ) {
        Text(
            text = text,
            modifier = Modifier.fillMaxWidth(),
            color = color,
            textAlign = textAlign,
            style = baseStyle
        )
    }
}

@Preview(device = WearDevices.LARGE_ROUND, showBackground = true)
@Composable
private fun ScrollableTextColumnPreview() {
    MaterialTheme(colorScheme = darkScheme, typography = baseline) {
        ScrollableTextColumn(
            text = "Line one.\nLine two.\nLine three.\nLine four.\nLine five.\nLine six.\nLine seven.\nLine eight.",
            maxLines = 2,
            modifier = Modifier.fillMaxWidth()
        )
    }
}
