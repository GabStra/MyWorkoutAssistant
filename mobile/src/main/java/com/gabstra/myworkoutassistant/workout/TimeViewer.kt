package com.gabstra.myworkoutassistant.workout

import android.annotation.SuppressLint
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.padding
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import kotlinx.coroutines.delay
import java.time.LocalDateTime
import java.time.Duration
import java.time.temporal.ChronoUnit

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

    val monospacedStyle = style.copy(fontFamily = FontFamily.Monospace)

    var showDots by remember { mutableStateOf(true) }

    // Coroutine that blinks at 2 Hz synced to half-second boundaries
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
            showDots = !showDots
            delay(Duration.between(now, nextHalfSecond).toMillis())
        }
    }

    Row(
        modifier = modifier,
        verticalAlignment = Alignment.CenterVertically,
        horizontalArrangement = Arrangement.spacedBy(2.dp)
    ) {

        if(hours > 0){
            Text(
                modifier = Modifier,
                text = String.format("%02d", hours),
                style = monospacedStyle,
                textAlign = TextAlign.Center,
                color =  color,
            )

            Text(
                text = ":",
                style = monospacedStyle,
                color = if (showDots) MaterialTheme.colorScheme.onBackground else MaterialTheme.colorScheme.surfaceContainer,
                textAlign = TextAlign.Center,
            )
        }

        Text(
            modifier = Modifier,
            text = String.format("%02d", minutes),
            style = monospacedStyle,
            textAlign = TextAlign.Center,
            color =  color,
        )

        Text(
            text = ":",
            style = monospacedStyle,
            color = if (showDots) MaterialTheme.colorScheme.onBackground else MaterialTheme.colorScheme.surfaceContainer,
            textAlign = TextAlign.Center,
            modifier = Modifier.padding(bottom = 3.dp),
        )

        Text(
            modifier = Modifier,
            text = String.format("%02d", remainingSeconds),
            style = monospacedStyle,
            textAlign = TextAlign.Center,
            color =  color,
        )
    }
}
