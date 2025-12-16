package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import kotlinx.coroutines.delay
import java.time.Duration
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit

@SuppressLint("DefaultLocale")
@Composable
fun CurrentTime() {
    var currentTime by remember { mutableStateOf(LocalDateTime.now()) }
    var showDots by remember { mutableStateOf(true) }

    LaunchedEffect(Unit) {
        while (true) {
            val now = LocalDateTime.now()
            val truncated = now.truncatedTo(ChronoUnit.SECONDS)
            val nanoOfSecond = now.nano
            val nextHalfSecond = if (nanoOfSecond < 500_000_000) {
                truncated.plusNanos(500_000_000)
            } else {
                truncated.plusSeconds(1)
            }
            currentTime = LocalDateTime.now()
            showDots = !showDots
            delay(Duration.between(now, nextHalfSecond).toMillis())
        }
    }

    val colonColor = if (showDots) MaterialTheme.colorScheme.onBackground else MaterialTheme.colorScheme.surfaceContainerHigh
    val textColor = MaterialTheme.colorScheme.onBackground

    val baseStyle = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium)
    val annotatedText = remember(showDots, currentTime.hour, currentTime.minute, colonColor, textColor, baseStyle) {
        buildAnnotatedString {
            withStyle(baseStyle.toSpanStyle().copy(color = textColor)) {
                append(String.format("%02d", currentTime.hour))
            }
            withStyle(baseStyle.toSpanStyle().copy(color = colonColor)) {
                append(":")
            }
            withStyle(baseStyle.toSpanStyle().copy(color = textColor)) {
                append(String.format("%02d", currentTime.minute))
            }
        }
    }

    Text(
        text = annotatedText,
        style = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium),
        textAlign = TextAlign.Center
    )
}


