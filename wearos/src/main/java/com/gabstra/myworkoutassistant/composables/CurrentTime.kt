package com.gabstra.myworkoutassistant.composables

import android.annotation.SuppressLint
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.withStyle
import androidx.wear.compose.material3.MaterialTheme
import androidx.wear.compose.material3.Text
import kotlinx.coroutines.delay
import java.time.LocalDateTime
import java.time.temporal.ChronoUnit

@SuppressLint("DefaultLocale")
@Composable
fun CurrentTime() {
    var currentTime by remember { mutableStateOf(LocalDateTime.now()) }

    var showDots by remember { mutableStateOf(true) }

    val captionStyle = MaterialTheme.typography.bodyMedium.copy(fontWeight = FontWeight.Medium)

    LaunchedEffect(Unit) {
        val now = LocalDateTime.now()
        val nextSecond = now.plusSeconds(1).truncatedTo(ChronoUnit.SECONDS)
        delay(java.time.Duration.between(now, nextSecond).toMillis())
        
        // Now use fixed delay
        while (true) {
            currentTime = LocalDateTime.now()
            showDots = !showDots
            delay(1000)
        }
    }

    val colonColor = if (showDots) MaterialTheme.colorScheme.onBackground else MaterialTheme.colorScheme.surfaceContainerHigh
    val textColor = MaterialTheme.colorScheme.onBackground

    val annotatedText = remember(showDots, currentTime.hour, currentTime.minute, colonColor, textColor) {
        buildAnnotatedString {
            withStyle(SpanStyle(color = textColor)) {
                append(String.format("%02d", currentTime.hour))
            }
            withStyle(SpanStyle(color = colonColor)) {
                append(":")
            }
            withStyle(SpanStyle(color = textColor)) {
                append(String.format("%02d", currentTime.minute))
            }
        }
    }

    Text(
        text = annotatedText,
        style = captionStyle,
        textAlign = TextAlign.Center
    )
}


