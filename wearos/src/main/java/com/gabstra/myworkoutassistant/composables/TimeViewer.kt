package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.withStyle
import androidx.wear.compose.material3.Text

@SuppressLint("DefaultLocale")
@Composable
fun TimeViewer(
    modifier: Modifier = Modifier,
    seconds: Int,
    color: Color,
    style: TextStyle,
) {
    val hours = seconds / 3600
    val minutes = (seconds % 3600) / 60
    val remainingSeconds = seconds % 60

    var showDots by remember { mutableStateOf(true) }

    // Coroutine that blinks at 2 Hz synced to half-second boundaries
/*    LaunchedEffect(Unit) {
        while (true) {
            val now = LocalDateTime.now()
            val truncated = now.truncatedTo(ChronoUnit.SECONDS)
            val nanoOfSecond = now.nano
            val nextHalfSecond = if (nanoOfSecond < 500_000_000) {
                truncated.plusNanos(500_000_000)
            } else {
                truncated.plusSeconds(1)
            }
            showDots = !showDots
            delay(Duration.between(now, nextHalfSecond).toMillis())
        }
    }*/

    val colonColor = color

    val annotatedText = remember(showDots, hours, minutes, remainingSeconds, color, colonColor, style) {
        buildAnnotatedString {
            if (hours > 0) {
                withStyle(style.toSpanStyle().copy(color = color)) {
                    append(String.format("%02d", hours))
                }
                withStyle(style.toSpanStyle().copy(color = colonColor)) {
                    append(":")
                }
            }
            withStyle(style.toSpanStyle().copy(color = color)) {
                append(String.format("%02d", minutes))
            }
            withStyle(style.toSpanStyle().copy(color = colonColor)) {
                append(":")
            }
            withStyle(style.toSpanStyle().copy(color = color)) {
                append(String.format("%02d", remainingSeconds))
            }
        }
    }

    Text(
        modifier = modifier,
        text = annotatedText,
        style = style,
        maxLines = 1
    )
}