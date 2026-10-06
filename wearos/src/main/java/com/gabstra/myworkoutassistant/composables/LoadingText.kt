package com.gabstra.myworkoutassistant.composables


import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import kotlinx.coroutines.delay

@Composable
fun LoadingText(
    baseText: String,
    modifier: Modifier = Modifier,
    style: TextStyle = MaterialTheme.typography.titleMedium,
    color: Color = Color.Unspecified,
    maxLines: Int = 1,
    textAlign: TextAlign? = null,
) {
    val dotCount = remember { mutableIntStateOf(1) }

    LaunchedEffect(Unit) {
        while (true) {
            delay(500)
            dotCount.intValue = (dotCount.intValue % 3) + 1  // cycles 1→2→3→1
        }
    }

    val animatedText = buildAnnotatedString {
        append(baseText)
        repeat(3) { dotIndex ->
            if (dotIndex >= dotCount.intValue) {
                pushStyle(SpanStyle(color = Color.Transparent))
            }
            append(".")
            if (dotIndex >= dotCount.intValue) {
                pop()
            }
        }
    }

    Text(
        modifier = modifier,
        text = animatedText,
        style = style,
        color = color,
        maxLines = maxLines,
        overflow = TextOverflow.Ellipsis,
        textAlign = textAlign,
    )
}
