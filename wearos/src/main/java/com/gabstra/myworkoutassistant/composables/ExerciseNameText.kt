package com.gabstra.myworkoutassistant.composables

import androidx.compose.foundation.basicMarquee
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.heightIn
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.rememberTextMeasurer
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text

@Composable
fun ExerciseNameText(
    text: String,
    modifier: Modifier = Modifier,
    style: TextStyle = MaterialTheme.typography.titleLarge.copy(
        fontWeight = FontWeight.SemiBold
    ),
    textAlign: TextAlign = TextAlign.Center,
) {
    val textMeasurer = rememberTextMeasurer()
    val density = LocalDensity.current

    val twoLineHeight = remember(textMeasurer, density, style) {
        with(density) {
            textMeasurer
                .measure(
                    text = "A\nA",
                    style = style,
                    maxLines = 2,
                )
                .size
                .height
                .toDp()
        }
    }

    Box(
        modifier = modifier.heightIn(max = twoLineHeight),
    ) {
        Text(
            modifier = Modifier
                .align(Alignment.BottomCenter)
                .fillMaxWidth().basicMarquee(iterations = Int.MAX_VALUE),
            text = text,
            style = style,
            textAlign = textAlign,
            maxLines = 2,
            overflow = TextOverflow.Ellipsis,
        )
    }
}
